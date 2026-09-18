import os
import re
from dataclasses import dataclass, field, replace

from db import get_conn, embedding_dim, vector_order_by
from intent import detect_intent, detect_service, load_aliases
from llm import chat, chat_stream, embed_one
from rank_bm25 import BM25Okapi
from tokenize_ko import tokenize

bm25 = None
bm25_corpus = []
# bm25_corpus 와 인덱스가 나란히 맞는 청크 메타. 본문이 같은 청크가 서로 다른 문서에
# 4.2% 존재하므로(중복 그룹 1,051개), 본문을 키로 쓰면 마지막 문서가 출처를 가로챈다.
bm25_meta: list["Candidate"] = []
EMBED_DIM = 0
# 청크 본문 -> (source, "카테고리/서비스", doc_type, section_path). UI 의 render_sources 와
# 문자열 호환 경로에서 쓴다. 본문이 겹치면 먼저 들어온 문서를 출처로 삼는다.
doc_meta = {}
TOP_K = 5

# 리랭킹 프롬프트에 넣을 문서당 최대 글자 수. RERANK_KEEP(12)건이면 약 11,000자.
RERANK_DOC_CHARS = 900

CANDIDATES = 20     # 벡터·BM25 각각 가져올 개수
RERANK_KEEP = 12    # 점수 보정 후 리랭킹에 넘길 개수
BOOST_BOTH = 1.2
BOOST_CONSOLE = 1.5
BOOST_SERVICE = 1.3

ALIASES: dict[str, str] = {}


# 답변 단계까지 들고 갈 청크 메타 컬럼 (스펙 4-4).
META_COLUMNS = "content, source_path, service, category, doc_type, section_path, source_url, images"


@dataclass
class Candidate:
    content: str
    source_path: str
    service: str       # "카테고리/서비스"
    doc_type: str
    score: float
    section_path: str = ""
    source_url: str | None = None
    # JSONB 에 저장된 모양 그대로: {path, caption, alt, missing}
    images: list = field(default_factory=list)


def _meta_candidate(row, score: float = 0.0) -> Candidate:
    """META_COLUMNS 순서인 행의 앞 8칸으로 Candidate 를 만든다."""
    content, source, service, category, doc_type, section_path, source_url, images = row[:8]
    return Candidate(
        content=content,
        source_path=source,
        service=f"{category}/{service}",
        doc_type=doc_type,
        score=score,
        section_path=section_path or "",
        source_url=source_url,
        images=list(images or []),
    )


def build_bm25():
    global bm25, bm25_corpus, bm25_meta, EMBED_DIM, ALIASES

    conn = get_conn()
    EMBED_DIM = embedding_dim(conn) or 0
    cur = conn.cursor()

    cur.execute(f"SELECT {META_COLUMNS} FROM documents")
    rows = cur.fetchall()

    doc_meta.clear()
    bm25_corpus = []
    bm25_meta = []
    for row in rows:
        cand = _meta_candidate(row)
        bm25_corpus.append(cand.content)
        bm25_meta.append(cand)
        doc_meta.setdefault(
            cand.content, (cand.source_path, cand.service, cand.doc_type, cand.section_path)
        )

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
    """문자열만 있는 호환 경로용. doc_meta 에서 메타를 되찾는다."""
    source, service, doc_type, section_path = doc_meta.get(
        content, ("(출처 미상)", "unknown", "other", "")
    )
    return Candidate(
        content=content, source_path=source, service=service,
        doc_type=doc_type, score=0.0, section_path=section_path,
    )


def embed_query(text):
    # 검색 질의는 input_type="query" 로 임베딩해야 적재 문서(passage)와 맞물린다.
    return embed_one(text, input_type="query")

def to_pgvector(vec):
    return "[" + ",".join(map(str, vec)) + "]"

def search_docs(query, service=None):
    """(상위 Candidate 목록, grounded). 청크 메타를 그대로 답변 단계로 넘긴다."""
    intent = detect_intent(query)
    svc = service or detect_service(query, ALIASES)
    candidates = hybrid_search(query, intent=intent, service=svc)
    return rerank_candidates(query, candidates, top_k=TOP_K)


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
        merged.append(replace(cand, score=score))

    merged.sort(key=lambda c: c.score, reverse=True)
    return merged[:keep]


def hybrid_search(query, intent="general", service=None, top_k=CANDIDATES, keep=RERANK_KEEP):
    conn = get_conn()
    cur = conn.cursor()

    q_vec = to_pgvector(embed_query(query))
    cur.execute(f"""
    SELECT {META_COLUMNS},
           1 - ({vector_order_by(EMBED_DIM)}) AS similarity
      FROM documents
     ORDER BY {vector_order_by(EMBED_DIM)}
     LIMIT %s;
    """, (q_vec, q_vec, top_k))

    vector_hits = []
    for row in cur.fetchall():
        cand = _meta_candidate(row)
        doc_meta.setdefault(
            cand.content, (cand.source_path, cand.service, cand.doc_type, cand.section_path)
        )
        vector_hits.append((cand, float(row[-1])))

    cur.close()
    conn.close()

    scores = bm25.get_scores(tokenize(query))
    top_idx = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]
    # 본문이 아니라 인덱스로 메타를 찾는다 — 본문이 같은 청크가 여러 문서에 있어서다.
    bm25_hits = [(bm25_meta[i], float(scores[i])) for i in top_idx if scores[i] > 0]

    return combine_scores(vector_hits, bm25_hits, intent, service, keep)

_ARRAY = re.compile(r"\[[\d\s.,]*\]")
# 라벨(점수/근거) 바로 뒤의 배열. JSON 형태('"점수": [...]')도 함께 잡는다.
_SCORE_LABEL = re.compile(r"점수[\"']?\s*:\s*(\[[\d\s.,]*\])")
_GROUNDED_LABEL = re.compile(r"근거[\"']?\s*:\s*(\[[\d\s.,]*\])")


def _numbers(array_text: str) -> list[float]:
    return [float(v) for v in re.findall(r"\d+(?:\.\d+)?", array_text)]


def _pair(scores_text: str, grounded_text: str, n: int):
    scores = _numbers(scores_text)
    grounded_raw = _numbers(grounded_text)
    if len(scores) != n or len(grounded_raw) != n:
        return None
    return scores, [v >= 1 for v in grounded_raw]


def parse_rerank(text: str, n: int):
    """응답에서 (점수, 근거) 배열을 읽는다. 둘 다 길이 n 일 때만 돌려준다.

    먼저 '점수:' / '근거:' 라벨 뒤의 배열을 찾는다 (모델이 설명이나 예시 배열을 덧붙여도
    엉뚱한 배열을 집지 않게). 라벨이 없으면 마지막 두 배열을 점수·근거 순으로 본다.
    """
    scores_hits = _SCORE_LABEL.findall(text)
    grounded_hits = _GROUNDED_LABEL.findall(text)
    if scores_hits and grounded_hits:
        parsed = _pair(scores_hits[-1], grounded_hits[-1], n)
        if parsed is not None:
            return parsed

    arrays = _ARRAY.findall(text)
    if len(arrays) < 2:
        return None
    return _pair(arrays[-2], arrays[-1], n)


def rerank_candidates(query, candidates: list[Candidate], top_k=TOP_K):
    """후보 전체를 추론 끈 한 번의 호출로 채점하고, 답이 있는 문서인지도 함께 받는다.

    반환: (상위 Candidate, grounded). grounded 는 상위 문서 중 '근거 있음' 이 하나라도
    있으면 True, 하나도 없으면 False, 응답을 못 읽었으면 None (검색 순서를 그대로 쓴다).
    """
    if not candidates:
        return [], False

    listing = "\n\n".join(
        f"[{i}] {c.content[:RERANK_DOC_CHARS]}" for i, c in enumerate(candidates)
    )
    prompt = f"""질문과 각 문서의 관련도를 0~10 점으로 평가하고, 그 문서만으로 질문에 답할 수 있는지(1/0)도 표시해.

질문:
{query}

문서 목록 ({len(candidates)}건):
{listing}

아래 두 줄만 출력해. 설명은 쓰지 마.
점수: [점수0, 점수1, ..., 점수{len(candidates) - 1}]
근거: [답가능0, 답가능1, ..., 답가능{len(candidates) - 1}]
"""

    try:
        parsed = parse_rerank(
            chat(prompt, temperature=0.0, max_tokens=512, think=False), len(candidates)
        )
    except Exception as e:
        print(f"  [리랭킹 실패] {type(e).__name__}: {e} → 검색 순서 사용")
        parsed = None

    if parsed is None:
        return candidates[:top_k], None

    scores, grounded = parsed
    order = sorted(range(len(candidates)), key=lambda i: scores[i], reverse=True)[:top_k]
    return [candidates[i] for i in order], any(grounded[i] for i in order)


def rerank(query, docs, top_k=TOP_K):
    """문자열 목록을 받는 호환 래퍼 (ui.py). 메타는 doc_meta 에서 되찾는다."""
    top, grounded = rerank_candidates(query, [_candidate(d) for d in docs], top_k=top_k)
    return [c.content for c in top], grounded

SYSTEM_PROMPT = (
    "너는 NHN Cloud 공식 문서를 근거로 답하는 기술 지원 어시스턴트다. "
    "반드시 제공된 문서 내용만 근거로 삼고, 문서에 없는 내용은 지어내지 말고 "
    "'제공된 문서에서 확인되지 않습니다'라고 밝혀라. "
    "이전 대화가 주어지면 '그것', '거기' 같은 지시어가 무엇을 가리키는지 그 맥락으로 해석해 이어서 답해라. "
    "단, 이전 대화 내용 자체를 근거로 삼지 말고 근거는 언제나 제공된 문서에서만 찾아라. "
    "각 문서 본문의 첫 줄 '문서명 > 섹션 경로'는 문서 안 위치이지 콘솔 메뉴 경로가 아니다. "
    "콘솔 메뉴 경로는 본문에 명시된 것만 써라. "
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


def _as_candidate(doc) -> Candidate:
    return doc if isinstance(doc, Candidate) else _candidate(doc)


def build_prompt(question, docs, history=None):
    """docs 는 Candidate 목록(정상 경로) 또는 문자열 목록(호환 경로) 이다.

    블록 머리말에 서비스·문서명·섹션·출처를 나란히 적어, 본문 첫 줄의
    '문서명 > 섹션 경로' 가 콘솔 메뉴 경로로 오해되지 않게 한다.
    """
    blocks = []
    for i, doc in enumerate(docs, 1):
        c = _as_candidate(doc)
        doc_title = os.path.splitext(os.path.basename(c.source_path))[0]
        blocks.append(
            f"[문서 {i}] 서비스: {c.service} · 문서: {doc_title} · "
            f"섹션: {c.section_path} · 출처: {c.source_path}\n{c.content}"
        )

    context = "\n\n".join(blocks)

    return f"""{format_history(history)}아래 문서를 근거로 질문에 답해라.

{context}

질문:
{question}
"""


def ask(question, history=None):
    # search_docs 는 Candidate 목록을 돌려주고, build_prompt 가 그대로 받는다.
    docs, _ = search_docs(retrieval_query(question, history), service=None)  # 필요하면 "Compute"

    return chat(build_prompt(question, docs, history), system=SYSTEM_PROMPT, max_tokens=2048)


def answer_stream(question, docs, history=None):
    """UI 에서 단계별 진행 표시를 하기 위해 검색 결과를 받아 답변만 스트리밍한다."""
    return chat_stream(build_prompt(question, docs, history), system=SYSTEM_PROMPT, max_tokens=2048)
