"""관리자 페이지 (스펙 4-3). questions 집계만 보여 준다. ADMIN_TOKEN 으로 보호한다(admin_auth)."""
import pandas as pd
import streamlit as st

import admin_auth
import admin_stats as s
import schema_ready
from db import get_conn


def _pct(v: float) -> str:
    return f"{v * 100:.0f}%"


def page():
    st.markdown(
        '<div class="nhn-header"><div class="nhn-logo">NHN</div>'
        '<div><div class="nhn-title">관리자</div>'
        '<div class="nhn-subtitle">질문 로그·피드백 집계</div></div></div>',
        unsafe_allow_html=True,
    )
    if not admin_auth.gate():
        return
    period = st.radio("기간", s.PERIODS, horizontal=True, index=1)
    since = s.since_for(period)

    # 스키마 보장(get_conn 포함) 부터 지표 집계 SQL 여섯 건까지 한 try 로 묶는다 —
    # 마이그레이션 전 DB(2B 컬럼 없음)에서 s.* 호출이 UndefinedColumn 으로 터져도
    # 트레이스백 대신 배너로 보여준다.
    conn = None
    try:
        schema_ready.ensure_schema()
        conn = get_conn()
        summary = s.summary(conn, since)
        services = s.by_service(conn, since)
        down = s.recent_down(conn, since)
        ungrounded = s.recent_ungrounded(conn, since)
        slow = s.recent_slow(conn, since)
        index = s.index_status(conn)
    except Exception as e:
        st.error("DB 에서 지표를 읽지 못했습니다.")
        st.caption(f"{type(e).__name__}: {e}")
        return
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    c = st.columns(4)
    c[0].metric("질문 수", f"{summary['questions']}")
    c[1].metric("세션 수", f"{summary['sessions']}")
    c[2].metric("응답 중앙값", f"{summary['median_s']}초")
    c[3].metric("응답 최대", f"{summary['max_s']}초")
    c = st.columns(4)
    c[0].metric("LLM 오류율", _pct(summary["error_rate"]))
    c[1].metric("미확인 비율", _pct(summary["ungrounded_rate"]))
    c[2].metric("👍", f"{summary['up']}")
    c[3].metric("👎", f"{summary['down']}")

    st.subheader("서비스별")
    st.dataframe(pd.DataFrame(services, columns=["서비스", "질문 수", "👎", "미확인"]),
                 width="stretch", hide_index=True)

    st.subheader("최근 👎 질문")
    st.dataframe(pd.DataFrame(down, columns=["시각", "질문", "서비스", "답변(앞 200자)"]),
                 width="stretch", hide_index=True)
    st.subheader("미확인으로 끝난 질문")
    st.dataframe(pd.DataFrame(ungrounded, columns=["시각", "질문", "서비스"]),
                 width="stretch", hide_index=True)
    st.subheader(f"{s.SLOW_MS // 1000}초 초과 질문")
    st.dataframe(pd.DataFrame(slow, columns=["시각", "질문", "소요(ms)"]),
                 width="stretch", hide_index=True)

    st.subheader("인덱스")
    last = index["last_ingested_at"]
    st.markdown(
        f'<div class="nhn-kv"><span>문서 청크</span><span>{index["chunks"]:,}</span></div>'
        f'<div class="nhn-kv"><span>서비스 수</span><span>{index["services"]}</span></div>'
        f'<div class="nhn-kv"><span>마지막 적재</span><span>{last.strftime("%Y-%m-%d %H:%M") if last else "기록 없음"}</span></div>',
        unsafe_allow_html=True,
    )
