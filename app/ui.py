import os
import time

import streamlit as st

from styles import CSS

st.set_page_config(
    page_title="NHN Cloud 문서 어시스턴트",
    page_icon="☁️",
    layout="centered",
    initial_sidebar_state="expanded",
)
st.markdown(CSS, unsafe_allow_html=True)

EXAMPLES = [
    "SMS 발송 API의 요청 파라미터를 알려줘",
    "오브젝트 스토리지에 파일을 업로드하는 방법은?",
    "인스턴스를 생성하는 절차를 알려줘",
    "API 호출에 필요한 인증 헤더는 무엇인가요?",
]


@st.cache_resource(show_spinner=False)
def load_index():
    """BM25 인덱스는 프로세스당 한 번만 만든다.

    (기존 코드는 메시지를 보낼 때마다 전체 코퍼스를 다시 읽어 인덱스를 새로 만들었다.)
    """
    import rag

    count = rag.build_bm25()
    return rag, count


USER_MARKER = '<span class="nhn-user-marker"></span>'


def user_bubble(text):
    """사용자 말풍선. CSS 가 역할을 구분할 수 있도록 마커를 함께 심는다."""
    with st.chat_message("user", avatar="🙋"):
        st.markdown(USER_MARKER, unsafe_allow_html=True)
        st.markdown(text)


def render_sources(docs, rag):
    if not docs:
        return

    with st.expander(f"참고한 문서 {len(docs)}건", expanded=False):
        for i, d in enumerate(docs, 1):
            source, service = rag.get_meta(d)
            name = os.path.basename(source).replace(".html", "")
            st.markdown(
                f'<div style="margin-bottom:0.6rem">'
                f'<span class="nhn-service-tag">{service}</span>'
                f'<span class="nhn-source-chip">{i}. {name}</span></div>',
                unsafe_allow_html=True,
            )
            st.caption(d[:300] + ("…" if len(d) > 300 else ""))


# ---------------------------------------------------------------- 헤더
st.markdown(
    '<div class="nhn-header">'
    '<div class="nhn-logo">NHN</div>'
    '<div><div class="nhn-title">NHN Cloud 문서 어시스턴트</div>'
    '<div class="nhn-subtitle">공식 문서를 근거로 답하는 RAG 챗봇</div></div>'
    "</div>",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------- 인덱스 로드
try:
    rag, doc_count = load_index()
    ready = True
    load_error = None
except Exception as e:
    rag, doc_count, ready, load_error = None, 0, False, e

# ---------------------------------------------------------------- 사이드바
with st.sidebar:
    st.markdown(
        '<div class="nhn-header" style="border:none;margin-bottom:0.5rem;padding-bottom:0">'
        '<div class="nhn-logo">NHN</div>'
        '<div><div class="nhn-title">Cloud Docs AI</div></div></div>',
        unsafe_allow_html=True,
    )

    st.markdown("### 인덱스")
    if ready:
        st.markdown(
            f'<div class="nhn-kv"><span>상태</span><span>연결됨</span></div>'
            f'<div class="nhn-kv"><span>문서 청크</span><span>{doc_count:,}</span></div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div class="nhn-kv"><span>상태</span><span>연결 실패</span></div>',
            unsafe_allow_html=True,
        )

    st.markdown("### 모델")
    from llm import EMBEDDING_MODEL_NAME, LLM_MODEL_NAME

    st.markdown(
        f'<div class="nhn-kv"><span>생성</span><span>{LLM_MODEL_NAME.split("/")[-1]}</span></div>'
        f'<div class="nhn-kv"><span>임베딩</span><span>{EMBEDDING_MODEL_NAME.split("/")[-1]}</span></div>',
        unsafe_allow_html=True,
    )

    st.markdown("### 검색 설정")
    top_k = st.slider("참고 문서 수", 3, 10, 5)
    candidates = st.slider("검색 후보 수", 5, 20, 20,
                           help="벡터·BM25 각각에서 가져올 개수. 늘리면 정확도가 오르지만 느려집니다.")

    st.divider()
    if st.button("대화 초기화", use_container_width=True):
        st.session_state.messages = []
        st.rerun()

# ---------------------------------------------------------------- DB 미연결 처리
if not ready:
    st.error(
        "문서 인덱스에 연결하지 못했습니다.\n\n"
        "`docker compose up -d` 로 pgvector 를 띄우고 "
        "`python ingest.py` 로 문서를 적재했는지 확인하세요."
    )
    st.caption(f"상세: {type(load_error).__name__}: {load_error}")
    st.stop()

# ---------------------------------------------------------------- 대화 상태
if "messages" not in st.session_state:
    st.session_state.messages = []

if "pending" not in st.session_state:
    st.session_state.pending = None

# ---------------------------------------------------------------- 빈 화면
if not st.session_state.messages:
    st.markdown(
        '<div class="nhn-empty"><h2>무엇을 도와드릴까요?</h2>'
        "<p>NHN Cloud 공식 문서에서 근거를 찾아 답변합니다.</p></div>",
        unsafe_allow_html=True,
    )

    cols = st.columns(2)
    for i, ex in enumerate(EXAMPLES):
        if cols[i % 2].button(ex, key=f"ex_{i}", use_container_width=True):
            st.session_state.pending = ex
            st.rerun()

# ---------------------------------------------------------------- 히스토리
for msg in st.session_state.messages:
    if msg["role"] == "user":
        user_bubble(msg["content"])
    else:
        with st.chat_message("assistant", avatar="☁️"):
            st.markdown(msg["content"])
            if msg.get("docs"):
                render_sources(msg["docs"], rag)

# ---------------------------------------------------------------- 입력
typed = st.chat_input("NHN Cloud 문서에 대해 질문하세요")
question = typed or st.session_state.pending
st.session_state.pending = None

if question:
    # 이번 질문을 넣기 전까지의 대화가 맥락이다.
    history = list(st.session_state.messages)
    st.session_state.messages.append({"role": "user", "content": question})

    user_bubble(question)

    with st.chat_message("assistant", avatar="☁️"):
        docs = []
        failed = False

        try:
            with st.status("문서를 검색하고 있습니다…", expanded=False) as status:
                t0 = time.time()

                search_q = rag.retrieval_query(question, history)
                intent = rag.detect_intent(question)
                # 후속 질문("그럼 삭제는?")은 직전 턴의 서비스를 이어받는다 (스펙 4-1).
                service = rag.detect_service(search_q, rag.ALIASES, fallback=st.session_state.get("last_service"))
                st.session_state.last_service = service
                status.update(label=f"1/3 하이브리드 검색 (벡터 + BM25) · {intent} · {service or '서비스 미상'}")
                candidates_found = rag.hybrid_search(search_q, intent=intent, service=service, top_k=candidates)
                docs = [c.content for c in candidates_found]

                status.update(label=f"2/3 관련도 평가 ({len(docs)}건)")
                docs, grounded = rag.rerank(search_q, docs, top_k=top_k)

                label = f"3/3 답변 생성 · {intent} · {service or '서비스 미상'} · 검색 {time.time() - t0:.1f}초"
                if search_q != question:
                    label += " · 이전 질문과 함께 검색"
                status.update(label=label, state="complete")

            if grounded is False:
                st.caption("관련도 평가 결과 근거가 될 문서를 찾지 못했습니다. 답변은 참고만 하세요.")
            elif grounded is None:
                st.caption("관련도 확인 실패 — 검색 순서를 그대로 사용했습니다.")

            answer = st.write_stream(rag.answer_stream(question, docs, history))
            render_sources(docs, rag)
        except Exception as e:
            # 모델 서버 혼잡(429/503)이 재시도로도 풀리지 않으면 화면을 깨뜨리지 않고 안내한다.
            answer = "⚠️ 모델 서버가 일시적으로 혼잡해 답변을 만들지 못했습니다. 잠시 후 다시 질문해 주세요."
            docs = []
            failed = True
            st.markdown(answer)
            st.caption(f"{type(e).__name__}: {e}")

    st.session_state.messages.append(
        {"role": "assistant", "content": answer, "docs": docs, "error": failed}
    )
