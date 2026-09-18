"""관리자 페이지 토큰 확인 (환경변수 ADMIN_TOKEN). 토큰이 비어 있으면 보호하지 않는다."""
import hmac, os
import streamlit as st

SESSION_KEY = "admin_ok"


def required_token() -> str:
    return os.getenv("ADMIN_TOKEN", "").strip()


def is_authorized() -> bool:
    token = required_token()
    return not token or bool(st.session_state.get(SESSION_KEY))


def gate() -> bool:
    """인증됐으면 True. 아니면 토큰 입력창을 그리고 False 를 돌려준다 (호출자는 return)."""
    if is_authorized():
        return True
    st.info("관리자 페이지입니다. 관리자 토큰을 입력하세요.")
    # Enter 를 쳐도, 확인 버튼을 눌러도 rerun 이 일어나므로 값이 있으면 매 rerun 에서 검사한다.
    # (버튼 클릭 여부에 매달면 Enter 로 제출한 사용자는 아무 반응도 못 본다.)
    # 붙여넣기 때 따라오는 앞뒤 공백·줄바꿈은 무시한다.
    typed = (st.text_input("관리자 토큰", type="password", key="admin_token_input") or "").strip()
    st.button("확인", key="admin_token_submit")
    if typed:
        if hmac.compare_digest(typed, required_token()):
            st.session_state[SESSION_KEY] = True
            st.rerun()
        st.error("토큰이 올바르지 않습니다.")
    return False
