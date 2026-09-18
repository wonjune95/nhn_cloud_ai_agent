"""Streamlit 진입점. 화면은 chat_page / admin_page 에 있다."""
import streamlit as st

from styles import CSS

st.set_page_config(
    page_title="NHN Cloud 콘솔 안내 봇",
    page_icon="☁️",
    layout="centered",
    initial_sidebar_state="auto"  # 모바일 폭에서는 접힌 채로 시작한다,
)
st.markdown(CSS, unsafe_allow_html=True)

import chat_page  # noqa: E402  (set_page_config 가 먼저여야 한다)
import admin_page  # noqa: E402

PAGES = [
    st.Page(chat_page.page, title="챗", icon="💬", default=True),
    st.Page(admin_page.page, title="관리자", icon="📊", url_path="admin"),
]

st.navigation(PAGES).run()
