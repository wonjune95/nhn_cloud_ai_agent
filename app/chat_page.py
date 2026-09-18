"""챗 화면 (스펙 3·4-1). ui.py 의 st.navigation 이 page() 를 부른다."""
import html
import os
import sys
import time
import uuid

import streamlit as st

import answer_render as ar
import db
import qlog
import schema_ready

# 컨테이너에서는 /docs, 로컬에서는 저장소 루트의 nhn_cloud_docs.
DOCS_DIR = os.getenv(
    "DOCS_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "nhn_cloud_docs"),
)

EXAMPLES = [
    "VPC에 서브넷을 추가하는 방법",
    "로드 밸런서를 생성하는 절차",
    "플로팅 IP를 인스턴스에 연결하는 방법",
    "Object Storage에 컨테이너를 만드는 방법",
]
INTENT_LABEL = {"console": "콘솔 절차", "general": "일반"}
AUTO = "자동"
CANDIDATES = 20  # 벡터·BM25 각각 가져올 개수 (슬라이더 제거, 고정)
USER_MARKER = '<span class="nhn-user-marker"></span>'


@st.cache_resource(show_spinner=False)
def load_index():
    """BM25 인덱스는 프로세스당 한 번. 같은 자리에서 2B 컬럼도 붙인다 (재적재 없이)."""
    import rag

    schema_ready.ensure_schema()
    count = rag.build_bm25()
    return rag, count


# ---------------------------------------------------------------- 그리기

def user_bubble(text):
    with st.chat_message("user", avatar="🙋"):
        st.markdown(USER_MARKER, unsafe_allow_html=True)
        st.markdown(text)


def service_tag(service, intent):
    st.markdown(
        f'<div class="nhn-answer-tag"><span class="nhn-service-tag">{html.escape(service or "서비스 미상", quote=True)}</span>'
        f'<span class="nhn-source-chip">{INTENT_LABEL.get(intent, intent)}</span></div>',
        unsafe_allow_html=True,
    )


def candidate_chip(c) -> str:
    name = os.path.splitext(os.path.basename(c.source_path))[0]
    section = (c.section_path or "").replace(" > ", " › ")
    return f"{c.service} · {name}" + (f" › {section}" if section else "")


def render_progress_chips(slot, cands, limit=5):
    """status 안의 자리(slot)에 후보 문서를 한 줄씩 그린다. 리랭킹 뒤 같은 자리를 다시 그린다.

    후보 문서 값은 코퍼스에서 온 것이라 HTML 로 그리기 전에 이스케이프한다(2A 패턴과 동일)."""
    slot.markdown(
        "".join(
            f'<div class="nhn-progress-chip">{html.escape(candidate_chip(c), quote=True)}</div>'
            for c in cands[:limit]
        ),
        unsafe_allow_html=True,
    )


def render_answer(text, image_map):
    """{{img:N}} 을 스크린샷으로 바꿔 그린다. 파일이 없으면 그 그림만 건너뛴다 (스펙 6절).

    part.path 는 문서 청크의 images 필드에서 온 값이라 신뢰하지 않는다 —
    '../' 로 DOCS_DIR 밖을 가리키면 무시하고, st.image 실패도 그 그림만 건너뛴다.
    """
    docs_root = os.path.realpath(DOCS_DIR)
    for kind, part in ar.split_markers(text, image_map or {}):
        if kind == "text":
            st.markdown(part)
            continue
        full = os.path.realpath(os.path.join(DOCS_DIR, part.path))
        if not full.startswith(docs_root + os.sep):
            print(f"  [스크린샷] 경로 밖: {full}", file=sys.stderr)
            continue
        if not os.path.isfile(full):
            print(f"  [스크린샷] 파일 없음: {full}", file=sys.stderr)
            continue
        try:
            st.image(full, caption=part.caption or None)
        except Exception as e:
            print(f"  [스크린샷] 표시 실패: {full}: {e}", file=sys.stderr)


def source_card_html(i: int, c) -> str:
    """출처 카드 한 줄. 값은 전부 코퍼스에서 온 것(서비스·문서명·섹션·URL)이지만 크롤링 원본이라
    믿지 않고 HTML 로 그리기 전에 이스케이프한다."""
    name = html.escape(os.path.splitext(os.path.basename(c.source_path))[0], quote=True)
    section = html.escape((c.section_path or "").replace(" > ", " › "), quote=True)
    service = html.escape(c.service, quote=True)
    link = (
        f' <a href="{html.escape(c.source_url, quote=True)}" target="_blank">원문 ↗</a>'
        if c.source_url else ""
    )
    return (
        f'<div class="nhn-cite-card"><span class="nhn-cite-no">[{i}]</span> '
        f'<b>{name}</b> <span class="nhn-service-tag">{service}</span> '
        f'<span class="nhn-section">› {section}</span>{link}</div>'
    )


def render_sources(cands):
    """답변 아래 항상 보이는 번호 카드. 번호는 프롬프트의 [문서 N] 과 같다 (cands 순서)."""
    if not cands:
        return
    st.markdown("".join(source_card_html(i, c) for i, c in enumerate(cands, 1)), unsafe_allow_html=True)


def feedback_key(question_id):
    """피드백 상태는 메시지 순번이 아니라 질문 id 로 건다.

    순번으로 걸면 '대화 초기화' 뒤 순번이 0 부터 다시 시작해, 새 답변이 지워진
    대화의 '의견 감사합니다' 를 물려받고 평가 자체가 불가능해진다.
    """
    return f"fb_q{question_id}"


def feedback_buttons(question_id):
    """👍/👎. 누르면 바로 저장하고 자리에 결과 문구를 남긴다."""
    if question_id is None:
        # 로그 저장(qlog.log_question)이 실패해 id 가 없으면 피드백을 걸 자리가 없다 (스펙 6절).
        st.caption("저장 실패 — 피드백을 기록할 수 없습니다")
        return
    key = feedback_key(question_id)
    if key in st.session_state:
        st.caption(st.session_state[key])
        return
    up, down, _ = st.columns([1, 1, 8])
    if up.button("👍", key=f"{key}_up"):
        _save_feedback(key, question_id, 1)
    if down.button("👎", key=f"{key}_down"):
        _save_feedback(key, question_id, -1)


def _save_feedback(key, question_id, value):
    st.session_state[key] = "의견 감사합니다" if qlog.set_feedback(question_id, value) else "저장 실패"
    st.rerun()


def render_assistant(msg):
    with st.chat_message("assistant", avatar="☁️"):
        service_tag(msg.get("service"), msg.get("intent", "general"))
        if msg.get("grounded") is None and not msg.get("error"):
            st.caption("관련도 확인 실패 — 검색 순서를 그대로 사용했습니다.")
        render_answer(msg["content"], msg.get("image_map"))
        # 실패한 턴은 cands 를 로그용으로만 들고 있다 — 기록을 다시 그릴 때도 출처를 보이면 안 된다.
        if msg.get("grounded") is not False and not msg.get("error"):
            render_sources(msg.get("cands") or [])
        feedback_buttons(msg.get("question_id"))


# ---------------------------------------------------------------- 페이지

def page():
    st.markdown(
        '<div class="nhn-header"><div class="nhn-logo">NHN</div>'
        '<div><div class="nhn-title">NHN Cloud 콘솔 안내 봇</div>'
        '<div class="nhn-subtitle">공식 문서를 근거로 콘솔 사용법을 안내합니다</div></div></div>',
        unsafe_allow_html=True,
    )

    try:
        rag, doc_count = load_index()
        ready, load_error = True, None
    except Exception as e:
        rag, doc_count, ready, load_error = None, 0, False, e

    with st.sidebar:
        st.markdown("### 인덱스")
        st.markdown(
            f'<div class="nhn-kv"><span>상태</span><span>{"연결됨" if ready else "연결 실패"}</span></div>'
            + (f'<div class="nhn-kv"><span>문서 청크</span><span>{doc_count:,}</span></div>' if ready else ""),
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
        services = sorted(set(rag.ALIASES.values())) if ready else []
        chosen = st.selectbox("서비스", [AUTO] + services, help="자동이면 질문에서 서비스를 추정합니다.")
        top_k = st.slider("참고 문서 수", 3, 10, 5)
        st.divider()
        if st.button("대화 초기화", width="stretch"):
            st.session_state.messages = []
            st.session_state.pop("last_service", None)
            for k in [k for k in st.session_state if str(k).startswith("fb_")]:
                st.session_state.pop(k, None)
            st.rerun()

    if not ready:
        st.error("문서 인덱스에 연결하지 못했습니다. DB 와 적재 상태를 확인하세요.")
        st.caption(f"상세: {type(load_error).__name__}: {load_error}")
        st.stop()

    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("pending", None)
    st.session_state.setdefault("session_id", uuid.uuid4().hex)

    if not st.session_state.messages:
        st.markdown(
            '<div class="nhn-empty"><h2>무엇을 도와드릴까요?</h2>'
            "<p>콘솔에서 어떻게 하는지 물어보세요. 메뉴 경로와 화면을 함께 안내합니다.</p></div>",
            unsafe_allow_html=True,
        )
        cols = st.columns(2)
        for i, ex in enumerate(EXAMPLES):
            if cols[i % 2].button(ex, key=f"ex_{i}", width="stretch"):
                st.session_state.pending = ex
                st.rerun()

    for msg in st.session_state.messages:
        if msg["role"] == "user":
            user_bubble(msg["content"])
        else:
            render_assistant(msg)

    typed = st.chat_input("NHN Cloud 콘솔 사용법을 질문하세요")
    question = typed or st.session_state.pending
    st.session_state.pending = None
    if question:
        answer_question(rag, question, chosen, top_k)


def answer_question(rag, question, chosen, top_k):
    history = list(st.session_state.messages)
    st.session_state.messages.append({"role": "user", "content": question})
    user_bubble(question)

    t0 = time.time()
    cands, image_map, grounded = [], {}, None
    service, intent, search_q = None, "general", question
    answer, failed, error_text = "", False, None
    holder = None

    with st.chat_message("assistant", avatar="☁️"):
        try:
            with st.status("검색 중…", expanded=False) as status:
                search_q = rag.retrieval_query(question, history)
                intent = rag.detect_intent(question)
                if chosen != AUTO:
                    # 드롭다운으로 고른 서비스는 이어받기용 기억에 남기지 않는다.
                    # (다시 '자동' 으로 돌아왔을 때 그 선택을 물려받으면 안 된다.)
                    service = chosen
                else:
                    service = rag.detect_service(search_q, rag.ALIASES, fallback=st.session_state.get("last_service"))
                    st.session_state.last_service = service
                status.update(label=f"검색 중 · {INTENT_LABEL.get(intent, intent)} · {service or '서비스 미상'}")
                found = rag.hybrid_search(search_q, intent=intent, service=service, top_k=CANDIDATES)
                chips = st.empty()
                render_progress_chips(chips, found)
                status.update(label=f"관련도 평가 중 ({len(found)}건)")
                cands, grounded = rag.rerank_candidates(search_q, found, top_k=top_k)
                render_progress_chips(chips, cands)
                status.update(label=f"답변 작성 중 · 검색 {time.time() - t0:.1f}초", state="complete")

            service_tag(service, intent)
            if grounded is False:
                # 근거 문서가 없으면 LLM 을 부르지 않는다 (스펙 3-3).
                answer = ar.NOT_GROUNDED_MESSAGE + (f" 관련 서비스: {service}" if service else "")
                cands = []
                st.markdown(answer)
            else:
                if grounded is None:
                    st.caption("관련도 확인 실패 — 검색 순서를 그대로 사용했습니다.")
                # 이웃 청크 이미지 차용은 답변을 만들 때만 필요하다 (거부 답변에는 그림이 없다).
                cands = rag.enrich_images(cands, intent)
                stream, image_map = rag.answer_stream(question, cands, history, intent=intent)
                holder = st.empty()
                with holder.container():
                    answer = st.write_stream(stream)
                holder.empty()
                with holder.container():
                    render_answer(answer, image_map)
                render_sources(cands)
        except Exception as e:
            answer = "⚠️ 모델 서버가 일시적으로 혼잡해 답변을 만들지 못했습니다. 잠시 후 다시 질문해 주세요."
            failed, error_text = True, f"{type(e).__name__}: {e}"
            # cands 는 검색이 성공했다는 뜻이니 로그(sources)를 위해 남긴다 — 화면에는
            # render_sources 를 안 불러서 어차피 안 보인다.
            image_map = {}
            if holder is not None:
                holder.empty()  # 도중까지 흘러나온 본문이 오류 문구 위에 남지 않게 지운다.
            st.markdown(answer)
            st.caption(error_text)

        question_id = qlog.log_question(
            session_id=st.session_state.session_id, question=question, retrieval_query=search_q,
            service=service, intent=intent, grounded=grounded, elapsed_ms=int((time.time() - t0) * 1000),
            sources=qlog.sources_of(cands), answer=answer, error=error_text,
        )
        feedback_buttons(question_id)

    st.session_state.messages.append({
        "role": "assistant", "content": answer, "cands": cands, "image_map": image_map,
        "service": service, "intent": intent, "grounded": grounded,
        "question_id": question_id, "error": failed,
    })
