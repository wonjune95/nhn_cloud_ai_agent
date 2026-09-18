"""관리자 페이지 집계 (스펙 4-3). questions 테이블만 읽는다. Streamlit 을 import 하지 않는다."""
from datetime import datetime, timedelta, timezone

PERIODS = ("7일", "30일", "전체")
SLOW_MS = 30000

# since 가 None 이면 전체 기간. 같은 파라미터를 두 번 넘겨 NULL 검사와 비교를 한 절로 처리한다.
_SINCE = "(%(since)s::timestamptz IS NULL OR asked_at >= %(since)s)"


def since_for(period: str) -> datetime | None:
    days = {"7일": 7, "30일": 30}.get(period)
    return None if days is None else datetime.now(timezone.utc) - timedelta(days=days)


def _rows(conn, sql, params):
    cur = conn.cursor()
    try:
        cur.execute(sql, params)
        return cur.fetchall()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


def summary(conn, since) -> dict:
    (n, sessions, median_ms, max_ms, errors, ungrounded, up, down), = _rows(conn, f"""
        SELECT count(*),
               count(DISTINCT session_id),
               percentile_cont(0.5) WITHIN GROUP (ORDER BY elapsed_ms),
               max(elapsed_ms),
               count(*) FILTER (WHERE error IS NOT NULL),
               count(*) FILTER (WHERE grounded = false),
               count(*) FILTER (WHERE feedback = 1),
               count(*) FILTER (WHERE feedback = -1)
          FROM questions WHERE {_SINCE}""", {"since": since})
    n = int(n)
    return {
        "questions": n,
        "sessions": int(sessions),
        "median_s": round(float(median_ms or 0) / 1000, 1),
        "max_s": round(float(max_ms or 0) / 1000, 1),
        "error_rate": (int(errors) / n) if n else 0.0,
        "ungrounded_rate": (int(ungrounded) / n) if n else 0.0,
        "up": int(up),
        "down": int(down),
    }


def by_service(conn, since) -> list[tuple[str, int, int, int]]:
    rows = _rows(conn, f"""
        SELECT coalesce(service, '(미상)'),
               count(*),
               count(*) FILTER (WHERE feedback = -1),
               count(*) FILTER (WHERE grounded = false)
          FROM questions WHERE {_SINCE}
         GROUP BY 1 ORDER BY 3 DESC, 2 DESC, 1""", {"since": since})
    return [(r[0], int(r[1]), int(r[2]), int(r[3])) for r in rows]


def daily(conn, since) -> list[tuple]:
    rows = _rows(conn, f"""
        SELECT (asked_at AT TIME ZONE 'Asia/Seoul')::date AS d,
               count(*),
               percentile_cont(0.5) WITHIN GROUP (ORDER BY elapsed_ms),
               count(*) FILTER (WHERE feedback = -1)
          FROM questions WHERE {_SINCE}
         GROUP BY 1 ORDER BY 1""", {"since": since})
    return [(r[0], int(r[1]), round(float(r[2] or 0) / 1000, 1), int(r[3])) for r in rows]


def search(conn, since, text, limit=50) -> list[tuple]:
    text = (text or "").strip()
    if not text:
        return []
    return _rows(conn, f"""
        SELECT asked_at, question, service, grounded, feedback
          FROM questions WHERE {_SINCE} AND question ILIKE %(pat)s
         ORDER BY asked_at DESC LIMIT %(limit)s""", {"since": since, "pat": f"%{text}%", "limit": limit})


def recent_down(conn, since, limit=20):
    return _rows(conn, f"""
        SELECT asked_at, question, service, left(coalesce(answer, ''), 200), coalesce(answer, ''), sources
          FROM questions WHERE {_SINCE} AND feedback = -1
         ORDER BY asked_at DESC LIMIT %(limit)s""", {"since": since, "limit": limit})


def recent_ungrounded(conn, since, limit=20):
    return _rows(conn, f"""
        SELECT asked_at, question, service
          FROM questions WHERE {_SINCE} AND grounded = false
         ORDER BY asked_at DESC LIMIT %(limit)s""", {"since": since, "limit": limit})


def recent_slow(conn, since, limit=20, threshold_ms=SLOW_MS):
    return _rows(conn, f"""
        SELECT asked_at, question, elapsed_ms
          FROM questions WHERE {_SINCE} AND elapsed_ms > %(threshold)s
         ORDER BY asked_at DESC LIMIT %(limit)s""", {"since": since, "limit": limit, "threshold": threshold_ms})


def index_status(conn) -> dict:
    (chunks, services, last), = _rows(
        conn, "SELECT count(*), count(DISTINCT service), max(ingested_at) FROM documents", {})
    return {"chunks": int(chunks), "services": int(services), "last_ingested_at": last}
