import re

from db import get_conn, embedding_dim, vector_order_by
from llm import chat, chat_stream, embed_one
from rank_bm25 import BM25Okapi
from tokenize_ko import tokenize

bm25 = None
bm25_corpus = []
EMBED_DIM = 0
# 청크 본문 -> (source, service). 검색 결과에 출처를 붙이기 위해 들고 있는다.
doc_meta = {}
TOP_K = 5

# 리랭킹 프롬프트에 넣을 문서당 최대 글자 수. 후보 20건이면 약 14,000자.
RERANK_DOC_CHARS = 700

def build_bm25():
    global bm25, bm25_corpus, EMBED_DIM

    conn = get_conn()
    EMBED_DIM = embedding_dim(conn) or 0
    cur = conn.cursor()

    cur.execute("SELECT content, source_path, service FROM documents")
    rows = cur.fetchall()

    bm25_corpus = [r[0] for r in rows]
    for content, source, service in rows:
        doc_meta[content] = (source, service)

    tokenized = [tokenize(doc) for doc in bm25_corpus]

    bm25 = BM25Okapi(tokenized)

    cur.close()
    conn.close()

    return len(bm25_corpus)


def get_meta(content):
    """청크 본문으로 (source, service) 를 되찾는다."""
    return doc_meta.get(content, ("(출처 미상)", "unknown"))

def embed_query(text):
    # 검색 질의는 input_type="query" 로 임베딩해야 적재 문서(passage)와 맞물린다.
    return embed_one(text, input_type="query")

def to_pgvector(vec):
    return "[" + ",".join(map(str, vec)) + "]"

def search_docs(query, service=None):
    candidates = hybrid_search(query, top_k=10)
    final_docs = rerank(query, candidates, top_k=TOP_K)
    return final_docs


def hybrid_search(query, top_k=10):
    conn = get_conn()
    cur = conn.cursor()

    # 🔥 vector 검색
    q_emb = embed_query(query)
    q_vec = to_pgvector(q_emb)

    cur.execute(f"""
    SELECT content, source_path, service
      FROM documents
     ORDER BY {vector_order_by(EMBED_DIM)}
     LIMIT %s;
    """, (q_vec, top_k))

    rows = cur.fetchall()
    vector_docs = [r[0] for r in rows]
    for content, source, service in rows:
        doc_meta.setdefault(content, (source, service))

    # 🔥 BM25 검색
    tokenized_query = tokenize(query)
    scores = bm25.get_scores(tokenized_query)

    bm25_top_idx = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]
    bm25_docs = [bm25_corpus[i] for i in bm25_top_idx]

    cur.close()
    conn.close()

    # 🔥 합치기 — set() 은 순서를 잃는다. 리랭킹이 실패했을 때 되돌아갈 순서가
    # 의미 있도록 벡터 결과를 앞에 두고 순서를 유지한 채 중복만 뺀다.
    combined = list(dict.fromkeys(vector_docs + bm25_docs))

    return combined

def parse_scores(text, n):
    """응답에서 마지막 숫자 배열을 찾아 길이가 n 이면 반환한다."""
    for match in reversed(re.findall(r"\[[\d\s.,]*\]", text)):
        values = [float(v) for v in re.findall(r"\d+(?:\.\d+)?", match)]
        if len(values) == n:
            return values
    return None

def rerank(query, docs, top_k=5):
    """후보 전체를 한 번의 호출로 채점한다.

    문서마다 따로 호출하면 질문 하나에 LLM 요청이 20번 가까이 나가고,
    NIM 무료 한도에서 429 가 연달아 터진다. 한 프롬프트에 번호를 붙여 넣고
    점수 배열 하나로 받는다. 파싱에 실패하면 검색 순서를 그대로 쓴다.
    """
    if len(docs) <= top_k:
        return docs

    listing = "\n\n".join(
        f"[{i}] {d[:RERANK_DOC_CHARS]}" for i, d in enumerate(docs)
    )

    prompt = f"""질문과 각 문서의 관련도를 0~10 점으로 평가해.

질문:
{query}

문서 목록 ({len(docs)}건):
{listing}

문서 번호 순서대로 점수만 담은 JSON 배열 하나만 출력해. 설명은 쓰지 마.
출력 형식: [점수0, 점수1, ..., 점수{len(docs) - 1}]
"""

    try:
        # Nemotron 은 추론 토큰을 먼저 소비하므로 본문이 잘리지 않게 여유를 둔다.
        scores = parse_scores(chat(prompt, temperature=0.0, max_tokens=4096), len(docs))
    except Exception as e:
        print(f"  [리랭킹 실패] {type(e).__name__}: {e} → 검색 순서 사용")
        scores = None

    if scores is None:
        return docs[:top_k]

    order = sorted(range(len(docs)), key=lambda i: scores[i], reverse=True)
    return [docs[i] for i in order[:top_k]]

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
    docs = search_docs(retrieval_query(question, history), service=None)  # 필요하면 "Compute"

    return chat(build_prompt(question, docs, history), system=SYSTEM_PROMPT, max_tokens=2048)


def answer_stream(question, docs, history=None):
    """UI 에서 단계별 진행 표시를 하기 위해 검색 결과를 받아 답변만 스트리밍한다."""
    return chat_stream(build_prompt(question, docs, history), system=SYSTEM_PROMPT, max_tokens=2048)

def langchain_search(query):
    # langchain 1.x 에서 langchain.schema 가 제거돼 langchain_core 로 옮겨졌다.
    from langchain_core.documents import Document

    docs = search_docs(query)
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
