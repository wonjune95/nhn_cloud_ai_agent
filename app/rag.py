import re
from dataclasses import dataclass

from db import get_conn, embedding_dim, vector_order_by
from intent import detect_intent, detect_service, load_aliases
from llm import chat, chat_stream, embed_one
from rank_bm25 import BM25Okapi
from tokenize_ko import tokenize

bm25 = None
bm25_corpus = []
EMBED_DIM = 0
# 청크 본문 -> (source, "카테고리/서비스", doc_type). 검색 결과에 출처를 붙이기 위해 들고 있는다.
doc_meta = {}
TOP_K = 5

# 리랭킹 프롬프트에 넣을 문서당 최대 글자 수. 후보 20건이면 약 14,000자.
RERANK_DOC_CHARS = 900

CANDIDATES = 20     # 벡터·BM25 각각 가져올 개수
RERANK_KEEP = 12    # 점수 보정 후 리랭킹에 넘길 개수
BOOST_BOTH = 1.2
BOOST_CONSOLE = 1.5
BOOST_SERVICE = 1.3

ALIASES: dict[str, str] = {}


@dataclass
class Candidate:
    content: str
    source_path: str
    service: str       # "카테고리/서비스"
    doc_type: str
    score: float


def build_bm25():
    global bm25, bm25_corpus, EMBED_DIM, ALIASES

    conn = get_conn()
    EMBED_DIM = embedding_dim(conn) or 0
    cur = conn.cursor()

    cur.execute("SELECT content, source_path, service, category, doc_type FROM documents")
    rows = cur.fetchall()

    bm25_corpus = [r[0] for r in rows]
    for content, source, service, category, doc_type in rows:
        doc_meta[content] = (source, f"{category}/{service}", doc_type)

    bm25 = BM25Okapi([tokenize(doc) for doc in bm25_corpus])
    ALIASES = load_aliases()

    cur.close()
    conn.close()

    return len(bm25_corpus)


def get_meta(content):
    """청크 본문으로 (source_path, '카테고리/서비스') 를 되찾는다."""
    meta = doc_meta.get(content)
    return (meta[0], meta[1]) if meta else ("(출처 미상)", "unknown")


def _candidate(content) -> Candidate:
    source, service, doc_type = doc_meta.get(content, ("(출처 미상)", "unknown", "other"))
    return Candidate(content=content, source_path=source, service=service, doc_type=doc_type, score=0.0)


def embed_query(text):
    # 검색 질의는 input_type="query" 로 임베딩해야 적재 문서(passage)와 맞물린다.
    return embed_one(text, input_type="query")

def to_pgvector(vec):
    return "[" + ",".join(map(str, vec)) + "]"

def search_docs(query, service=None):
    intent = detect_intent(query)
    svc = service or detect_service(query, ALIASES)
    candidates = hybrid_search(query, intent=intent, service=svc)
    return rerank(query, [c.content for c in candidates], top_k=TOP_K)


def combine_scores(vector_hits, bm25_hits, intent, service, keep=RERANK_KEEP):
    """벡터·BM25 결과를 하나의 점수로 합친다. 필터가 아니라 가중치만 준다."""
    max_bm25 = max((s for _, s in bm25_hits), default=0.0)
    vec = {c.content: (c, sim) for c, sim in vector_hits}
    kw = {c.content: (c, (s / max_bm25 if max_bm25 > 0 else 0.0)) for c, s in bm25_hits}

    merged: list[Candidate] = []
    for content in list(dict.fromkeys(list(vec) + list(kw))):
        cand = (vec.get(content) or kw.get(content))[0]
        base = max(vec.get(content, (None, 0.0))[1], kw.get(content, (None, 0.0))[1])
        score = base
        if content in vec and content in kw:
            score *= BOOST_BOTH
        if intent == "console" and cand.doc_type == "console":
            score *= BOOST_CONSOLE
        if service and cand.service == service:
            score *= BOOST_SERVICE
        merged.append(Candidate(cand.content, cand.source_path, cand.service, cand.doc_type, score))

    merged.sort(key=lambda c: c.score, reverse=True)
    return merged[:keep]


def hybrid_search(query, intent="general", service=None, top_k=CANDIDATES, keep=RERANK_KEEP):
    conn = get_conn()
    cur = conn.cursor()

    q_vec = to_pgvector(embed_query(query))
    cur.execute(f"""
    SELECT content, source_path, service, category, doc_type,
           1 - ({vector_order_by(EMBED_DIM)}) AS similarity
      FROM documents
     ORDER BY {vector_order_by(EMBED_DIM)}
     LIMIT %s;
    """, (q_vec, q_vec, top_k))

    vector_hits = []
    for content, source, svc, category, doc_type, sim in cur.fetchall():
        doc_meta.setdefault(content, (source, f"{category}/{svc}", doc_type))
        vector_hits.append((_candidate(content), float(sim)))

    cur.close()
    conn.close()

    scores = bm25.get_scores(tokenize(query))
    top_idx = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]
    bm25_hits = [(_candidate(bm25_corpus[i]), float(scores[i])) for i in top_idx if scores[i] > 0]

    return combine_scores(vector_hits, bm25_hits, intent, service, keep)

_ARRAY = re.compile(r"\[[\d\s.,]*\]")


def _numbers(array_text: str) -> list[float]:
    return [float(v) for v in re.findall(r"\d+(?:\.\d+)?", array_text)]


def parse_rerank(text: str, n: int):
    """응답의 마지막 두 숫자 배열을 (점수, 근거) 로 읽는다. 둘 다 길이 n 일 때만 돌려준다.

    순서는 프롬프트가 고정한다: 점수 줄이 먼저, 근거 줄이 나중.
    """
    arrays = _ARRAY.findall(text)
    if len(arrays) < 2:
        return None

    scores = _numbers(arrays[-2])
    grounded_raw = _numbers(arrays[-1])
    if len(scores) != n or len(grounded_raw) != n:
        return None
    return scores, [v >= 1 for v in grounded_raw]


def rerank(query, docs, top_k=TOP_K):
    """후보 전체를 추론 끈 한 번의 호출로 채점하고, 답이 있는 문서인지도 함께 받는다.

    반환: (상위 문서, grounded). grounded 는 상위 문서 중 '근거 있음' 이 하나라도 있으면 True,
    하나도 없으면 False, 응답을 못 읽었으면 None (검색 순서를 그대로 쓴다).
    """
    if not docs:
        return [], False

    listing = "\n\n".join(f"[{i}] {d[:RERANK_DOC_CHARS]}" for i, d in enumerate(docs))
    prompt = f"""질문과 각 문서의 관련도를 0~10 점으로 평가하고, 그 문서만으로 질문에 답할 수 있는지(1/0)도 표시해.

질문:
{query}

문서 목록 ({len(docs)}건):
{listing}

아래 두 줄만 출력해. 설명은 쓰지 마.
점수: [점수0, 점수1, ..., 점수{len(docs) - 1}]
근거: [답가능0, 답가능1, ..., 답가능{len(docs) - 1}]
"""

    try:
        parsed = parse_rerank(chat(prompt, temperature=0.0, max_tokens=512, think=False), len(docs))
    except Exception as e:
        print(f"  [리랭킹 실패] {type(e).__name__}: {e} → 검색 순서 사용")
        parsed = None

    if parsed is None:
        return docs[:top_k], None

    scores, grounded = parsed
    order = sorted(range(len(docs)), key=lambda i: scores[i], reverse=True)[:top_k]
    return [docs[i] for i in order], any(grounded[i] for i in order)

SYSTEM_PROMPT = (
    "너는 NHN Cloud 공식 문서를 근거로 답하는 기술 지원 어시스턴트다. "
    "반드시 제공된 문서 내용만 근거로 삼고, 문서에 없는 내용은 지어내지 말고 "
    "'제공된 문서에서 확인되지 않습니다'라고 밝혀라. "
    "이전 대화가 주어지면 '그것', '거기' 같은 지시어가 무엇을 가리키는지 그 맥락으로 해석해 이어서 답해라. "
    "단, 이전 대화 내용 자체를 근거로 삼지 말고 근거는 언제나 제공된 문서에서만 찾아라. "
    "답변은 한국어로 하고, 절차는 번호 목록으로, 파라미터·필드는 표로 정리해라."
)

# 프롬프트에 넣을 이전 대화 범위. 답변은 길어서 앞부분만 넣는다.
HISTORY_TURNS = 3
HISTORY_ANSWER_CHARS = 600

# 이런 표현이 들어간 짧은 질문은 앞 질문을 이어받는 후속 질문으로 본다.
FOLLOWUP_HINTS = (
    "그럼", "그러면", "그렇다면", "그건", "그거", "그것", "그 ", "이건", "이거",
    "저거", "해당", "위의", "위에", "아까", "방금", "여기서", "거기", "얘",
)


def last_user_question(history):
    for msg in reversed(history or []):
        if msg["role"] == "user":
            return msg["content"]
    return None


def retrieval_query(question, history=None):
    """검색에 쓸 질의를 만든다.

    "그건 콘솔에서는 어떻게 해?" 같은 후속 질문은 그 자체로는 검색어가 되지 못한다.
    LLM 으로 질문을 다시 쓰면 호출이 한 번 늘어 요청 한도를 더 먹으므로,
    후속 질문으로 보이면 직전 질문을 앞에 붙이는 방식으로 대신한다.
    """
    prev = last_user_question(history)
    if not prev:
        return question

    looks_followup = len(question) < 20 or any(h in question for h in FOLLOWUP_HINTS)
    return f"{prev} {question}" if looks_followup else question


def format_history(history):
    turns = [m for m in (history or []) if not m.get("error")][-HISTORY_TURNS * 2:]
    if not turns:
        return ""

    lines = []
    for m in turns:
        text = m["content"]
        if m["role"] == "assistant" and len(text) > HISTORY_ANSWER_CHARS:
            text = text[:HISTORY_ANSWER_CHARS] + " …(생략)"
        lines.append(("사용자: " if m["role"] == "user" else "어시스턴트: ") + text)

    return "이전 대화:\n" + "\n\n".join(lines) + "\n\n"


def build_prompt(question, docs, history=None):
    blocks = []
    for i, d in enumerate(docs, 1):
        source, service = get_meta(d)
        blocks.append(f"[문서 {i}] (서비스: {service} / 출처: {source})\n{d}")

    context = "\n\n".join(blocks)

    return f"""{format_history(history)}아래 문서를 근거로 질문에 답해라.

{context}

질문:
{question}
"""


def ask(question, history=None):
    docs, _ = search_docs(retrieval_query(question, history), service=None)  # 필요하면 "Compute"

    return chat(build_prompt(question, docs, history), system=SYSTEM_PROMPT, max_tokens=2048)


def answer_stream(question, docs, history=None):
    """UI 에서 단계별 진행 표시를 하기 위해 검색 결과를 받아 답변만 스트리밍한다."""
    return chat_stream(build_prompt(question, docs, history), system=SYSTEM_PROMPT, max_tokens=2048)

def langchain_search(query):
    # langchain 1.x 에서 langchain.schema 가 제거돼 langchain_core 로 옮겨졌다.
    from langchain_core.documents import Document

    docs, _ = search_docs(query)
    return [Document(page_content=d) for d in docs]

def ask_langchain(question):
    docs = langchain_search(question)

    context = "\n\n".join([d.page_content for d in docs])

    return chat(f"""
문서를 기반으로만 답해.

{context}

질문:
{question}
""", max_tokens=2048)
