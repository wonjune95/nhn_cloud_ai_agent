"""관리자 집계. 실제 pgvector 필요:  DB_HOST=localhost python -m pytest -m integration app/tests/test_admin_stats_db.py"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

pytestmark = pytest.mark.integration

# 자정 근처(KST)에 도는 test_daily_groups_by_kst_date 가 "오늘" 행을 두 날짜로 쪼개지 않도록
# KST 정오로 고정한다(10일 전 값도 같은 시각이라 안전).
NOW = datetime.now(ZoneInfo("Asia/Seoul")).replace(hour=12, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def insert(conn, **kw):
    row = dict(asked_at=NOW, session_id="s", question="q", service="Network/VPC", intent="console",
               grounded=True, elapsed_ms=1000, sources="[]", answer="a", error=None, feedback=None)
    row.update(kw)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO questions (asked_at, session_id, question, service, intent, grounded, elapsed_ms, sources, "
        "answer, error, feedback) VALUES (%(asked_at)s, %(session_id)s, %(question)s, %(service)s, %(intent)s, "
        "%(grounded)s, %(elapsed_ms)s, %(sources)s, %(answer)s, %(error)s, %(feedback)s)", row)
    conn.commit()
    cur.close()


@pytest.fixture
def seeded(conn):
    import db
    db.init_schema(conn, dim=8, rebuild=True)
    cur = conn.cursor()
    cur.execute("DELETE FROM questions")
    conn.commit()
    cur.close()
    insert(conn, session_id="a", elapsed_ms=1000, feedback=1)
    insert(conn, session_id="a", elapsed_ms=3000, feedback=-1, answer="긴 답변" * 100)
    insert(conn, session_id="b", elapsed_ms=40000, grounded=False, service="Storage/Object Storage")
    insert(conn, session_id="b", elapsed_ms=500, error="RateLimitError", grounded=None, service=None)
    insert(conn, session_id="c", elapsed_ms=2000, asked_at=NOW - timedelta(days=10), feedback=-1)
    return conn


def test_since_for_periods():
    import admin_stats as s
    assert s.since_for("전체") is None
    assert abs((datetime.now(timezone.utc) - s.since_for("7일")).days - 7) <= 0
    assert abs((datetime.now(timezone.utc) - s.since_for("30일")).days - 30) <= 0


def test_summary_all(seeded):
    import admin_stats as s
    r = s.summary(seeded, None)
    assert r["questions"] == 5 and r["sessions"] == 3
    assert r["median_s"] == 2.0 and r["max_s"] == 40.0
    assert r["error_rate"] == pytest.approx(0.2)
    assert r["ungrounded_rate"] == pytest.approx(0.2)
    assert r["up"] == 1 and r["down"] == 2


def test_summary_last_7_days_excludes_old_row(seeded):
    import admin_stats as s
    r = s.summary(seeded, s.since_for("7일"))
    assert r["questions"] == 4 and r["down"] == 1


def test_summary_empty_period_is_zero_not_error(seeded):
    import admin_stats as s
    r = s.summary(seeded, datetime.now(timezone.utc) + timedelta(days=1))
    assert r == {"questions": 0, "sessions": 0, "median_s": 0.0, "max_s": 0.0,
                 "error_rate": 0.0, "ungrounded_rate": 0.0, "up": 0, "down": 0}


def test_by_service_orders_by_down_then_count(seeded):
    import admin_stats as s
    rows = s.by_service(seeded, None)
    assert rows[0] == ("Network/VPC", 3, 2, 0)
    assert ("Storage/Object Storage", 1, 0, 1) in rows
    assert ("(미상)", 1, 0, 0) in rows


def test_recent_lists(seeded):
    import admin_stats as s
    down = s.recent_down(seeded, None)
    assert len(down) == 2 and len(down[0][3]) <= 200
    assert [r[1] for r in s.recent_ungrounded(seeded, None)] == ["q"]
    slow = s.recent_slow(seeded, None)
    assert len(slow) == 1 and slow[0][2] == 40000
    assert s.recent_down(seeded, None, limit=1) and len(s.recent_down(seeded, None, limit=1)) == 1


def test_index_status_reads_documents(seeded):
    import admin_stats as s
    r = s.index_status(seeded)
    assert r["chunks"] == 0 and r["services"] == 0 and r["last_ingested_at"] is None


def test_rows_rolls_back_on_error_so_connection_stays_usable(seeded):
    import admin_stats as s
    with pytest.raises(Exception):
        s._rows(seeded, "SELECT * FROM no_such_table", {})
    assert s.summary(seeded, None)["questions"] == 5


def test_daily_groups_by_kst_date(seeded):
    import admin_stats as s
    rows = s.daily(seeded, None)
    assert len(rows) == 2                      # 오늘 4건 + 10일 전 1건
    today = rows[-1]
    assert today[1] == 4 and today[3] == 1     # 질문 4, 👎 1 (오늘 것만)
    assert isinstance(today[2], float)


def test_search_matches_question_text(seeded):
    import admin_stats as s
    assert s.search(seeded, None, "") == []
    rows = s.search(seeded, None, "q")
    assert len(rows) == 5 and all(len(r) == 5 for r in rows)
    assert s.search(seeded, None, "없는말") == []


def test_recent_down_carries_full_answer_and_sources(seeded):
    import admin_stats as s
    row = s.recent_down(seeded, None)[0]
    assert len(row) == 6 and len(row[3]) <= 200 and row[4].startswith("긴 답변") and row[5] == []
