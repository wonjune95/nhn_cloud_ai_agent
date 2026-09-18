"""questions 로그·피드백·컬럼 추가. 실제 pgvector 필요:  DB_HOST=localhost python -m pytest -m integration app/tests/test_qlog_db.py"""
import pytest

pytestmark = pytest.mark.integration


@pytest.fixture
def schema(conn):
    import db
    db.init_schema(conn, dim=8, rebuild=True)
    cur = conn.cursor()
    cur.execute("DELETE FROM questions")
    conn.commit()
    cur.close()
    return conn


def columns(conn, table):
    cur = conn.cursor()
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = %s", (table,))
    out = {r[0] for r in cur.fetchall()}
    cur.close()
    return out


def test_init_schema_adds_2b_columns(schema):
    assert {"session_id", "answer", "retrieval_query"} <= columns(schema, "questions")
    assert "ingested_at" in columns(schema, "documents")


def test_migrate_is_idempotent(schema):
    import db
    db.migrate(schema)
    db.migrate(schema)
    assert "session_id" in columns(schema, "questions")


def test_migrate_skips_when_tables_missing(conn):
    """questions 가 없는 빈 DB 에서도 UI 기동이 죽지 않는다."""
    import db
    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS questions")
    cur.execute("DROP TABLE IF EXISTS documents")
    conn.commit()
    cur.close()
    db.migrate(conn)  # 예외 없이 끝나면 통과


def test_log_question_inserts_and_returns_id(schema):
    import qlog
    from rag import Candidate
    c = Candidate(content="본문", source_path="Network/VPC/콘솔 사용 가이드.html", service="Network/VPC",
                  doc_type="console", score=1.0, section_path="서브넷 생성", source_url="https://x/")

    qid = qlog.log_question(session_id="s1", question="서브넷?", retrieval_query="서브넷?", service="Network/VPC",
                            intent="console", grounded=True, elapsed_ms=1234, sources=qlog.sources_of([c]),
                            answer="콘솔 > Network > VPC")

    assert isinstance(qid, int)
    cur = schema.cursor()
    cur.execute("SELECT session_id, question, service, intent, grounded, elapsed_ms, sources, answer, error, feedback "
                "FROM questions WHERE id = %s", (qid,))
    row = cur.fetchone()
    cur.close()
    assert row[0] == "s1" and row[1] == "서브넷?" and row[2] == "Network/VPC" and row[3] == "console"
    assert row[4] is True and row[5] == 1234
    assert row[6] == [{"source_path": "Network/VPC/콘솔 사용 가이드.html", "section_path": "서브넷 생성",
                       "source_url": "https://x/", "service": "Network/VPC"}]
    assert row[7] == "콘솔 > Network > VPC" and row[8] is None and row[9] is None


def test_log_question_records_error_and_null_grounded(schema):
    import qlog
    qid = qlog.log_question(session_id="s1", question="q", retrieval_query="q", service=None, intent="general",
                            grounded=None, elapsed_ms=10, sources=[], answer="", error="RateLimitError: 429")
    cur = schema.cursor()
    cur.execute("SELECT grounded, error, service FROM questions WHERE id = %s", (qid,))
    assert cur.fetchone() == (None, "RateLimitError: 429", None)
    cur.close()


def test_set_feedback_updates_row(schema):
    import qlog
    qid = qlog.log_question(session_id="s", question="q", retrieval_query="q", service=None, intent="general",
                            grounded=True, elapsed_ms=1, sources=[], answer="a")
    assert qlog.set_feedback(qid, -1) is True
    cur = schema.cursor()
    cur.execute("SELECT feedback FROM questions WHERE id = %s", (qid,))
    assert cur.fetchone()[0] == -1
    cur.close()


def test_log_failures_do_not_raise(monkeypatch, capsys):
    import qlog

    def boom():
        raise RuntimeError("DB 죽음")

    monkeypatch.setattr(qlog, "get_conn", boom)
    assert qlog.log_question(session_id="s", question="q", retrieval_query="q", service=None, intent="general",
                             grounded=True, elapsed_ms=1, sources=[], answer="a") is None
    assert qlog.set_feedback(1, 1) is False
    assert "질문 로그" in capsys.readouterr().err


def test_log_question_closes_connection_when_execute_fails(schema, monkeypatch):
    """cursor()/execute 가 실 연결을 얻은 뒤 실패해도 그 연결은 닫혀야 한다 (연결 누수 방지)."""
    import qlog
    from db import get_conn as real_get_conn

    class FailingConn:
        """실 연결을 감싸되 cursor() 에서 터진다. close() 호출 여부만 기록한다."""

        def __init__(self, real):
            self._real = real
            self.closed = False

        def cursor(self):
            raise RuntimeError("cursor 실패")

        def close(self):
            self.closed = True
            self._real.close()

    wrapper = FailingConn(real_get_conn())
    monkeypatch.setattr(qlog, "get_conn", lambda: wrapper)

    result = qlog.log_question(session_id="s", question="q", retrieval_query="q", service=None,
                                intent="general", grounded=True, elapsed_ms=1, sources=[], answer="a")

    assert result is None
    assert wrapper.closed is True
