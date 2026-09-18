"""관리자 페이지 (스펙 4-3). questions 집계만 보여 준다. ADMIN_TOKEN 으로 보호한다(admin_auth)."""
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

import admin_auth
import admin_stats as s
import schema_ready
from db import get_conn

# admin_stats.daily 가 'Asia/Seoul' 기준으로 날짜를 묶으므로, 화면에 찍는 다른 시각도
# 같은 시간대로 맞춘다 — 안 그러면 같은 질문이 daily 차트와 표에서 서로 다른 날짜로 보인다.
KST = ZoneInfo("Asia/Seoul")


def _pct(v: float) -> str:
    return f"{v * 100:.0f}%"


def _kst(dt):
    return dt.astimezone(KST)


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
    q = st.text_input("질문 검색", placeholder="질문에 포함된 단어")

    # 스키마 보장(get_conn 포함) 부터 지표 집계 SQL 까지 한 try 로 묶는다 —
    # 마이그레이션 전 DB(2B 컬럼 없음)에서 s.* 호출이 UndefinedColumn 으로 터져도
    # 트레이스백 대신 배너로 보여준다. 검색어가 바뀌면 다시 열려야 하므로
    # 위젯은 먼저 읽고, 검색 쿼리도 이 try 안에서 실행한다.
    conn = None
    try:
        schema_ready.ensure_schema()
        conn = get_conn()
        summary = s.summary(conn, since)
        services = s.by_service(conn, since)
        daily = s.daily(conn, since)
        down = s.recent_down(conn, since)
        ungrounded = s.recent_ungrounded(conn, since)
        slow = s.recent_slow(conn, since)
        index = s.index_status(conn)
        found = s.search(conn, since, q)
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

    st.subheader("일별 추이")
    if not daily:
        st.info("기간 안에 질문이 없습니다")
    else:
        df = pd.DataFrame(daily, columns=["일자", "질문 수", "응답 중앙값(초)", "👎"]).set_index("일자")
        st.bar_chart(df[["질문 수"]], height=220)
        st.bar_chart(df[["응답 중앙값(초)"]], height=220)
        st.bar_chart(df[["👎"]], height=220)

    st.subheader("서비스별")
    st.dataframe(pd.DataFrame(services, columns=["서비스", "질문 수", "👎", "미확인"]),
                 width="stretch", hide_index=True)

    st.subheader("최근 👎 질문")
    if not down:
        st.info("👎 받은 질문이 없습니다")
    else:
        for asked_at, question, service, _answer200, answer_full, sources in down:
            with st.expander(f"{_kst(asked_at):%m-%d %H:%M} · {question[:40]} · {service or '-'}"):
                st.markdown(answer_full)
                st.json(sources)

    if q:
        st.subheader("검색 결과")
        st.dataframe(
            pd.DataFrame([(_kst(r[0]), *r[1:]) for r in found],
                         columns=["시각", "질문", "서비스", "근거", "피드백"]),
            width="stretch", hide_index=True)

    st.subheader("미확인으로 끝난 질문")
    st.dataframe(pd.DataFrame([(_kst(r[0]), *r[1:]) for r in ungrounded], columns=["시각", "질문", "서비스"]),
                 width="stretch", hide_index=True)
    st.subheader(f"{s.SLOW_MS // 1000}초 초과 질문")
    st.dataframe(pd.DataFrame([(_kst(r[0]), *r[1:]) for r in slow], columns=["시각", "질문", "소요(ms)"]),
                 width="stretch", hide_index=True)

    st.subheader("인덱스")
    last = index["last_ingested_at"]
    st.markdown(
        f'<div class="nhn-kv"><span>문서 청크</span><span>{index["chunks"]:,}</span></div>'
        f'<div class="nhn-kv"><span>서비스 수</span><span>{index["services"]}</span></div>'
        f'<div class="nhn-kv"><span>마지막 적재</span><span>{last.strftime("%Y-%m-%d %H:%M") if last else "기록 없음"}</span></div>',
        unsafe_allow_html=True,
    )
