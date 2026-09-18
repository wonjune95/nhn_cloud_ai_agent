"""챗·관리자 두 페이지가 함께 쓰는 스키마 보장 진입점.

db.py 는 streamlit 을 몰라야 하므로(단위 테스트가 streamlit 없이 db.py 를 그대로
쓴다), @st.cache_resource 로 감싸는 얇은 껍데기를 여기 따로 둔다.
"""
import streamlit as st

import db


@st.cache_resource(show_spinner=False)
def ensure_schema():
    """questions/documents 의 2B 컬럼을 프로세스당 한 번만 붙인다."""
    conn = db.get_conn()
    try:
        db.migrate(conn)
    finally:
        conn.close()
