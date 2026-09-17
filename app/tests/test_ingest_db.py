"""실제 pgvector + 임베딩 API 가 필요하다.  python -m pytest -m integration app/tests/test_ingest_db.py"""
import json
import os

import pytest

pytestmark = pytest.mark.integration

HTML = """<section>
<h2>Network &gt; VPC &gt; 콘솔 사용 가이드</h2>
<h3>서브넷 생성</h3>
<p>서브넷 생성 버튼을 클릭합니다. <img src="./images/s1.png" alt=""></p>
<h3>서브넷 삭제</h3>
<p>삭제를 클릭합니다.</p>
</section>"""


@pytest.fixture
def docs_dir(tmp_path):
    doc = tmp_path / "Network" / "VPC"
    doc.mkdir(parents=True)
    (doc / "콘솔 사용 가이드.html").write_text(HTML, encoding="utf-8")
    (tmp_path / "manifest.json").write_text(json.dumps({
        "https://docs.nhncloud.com/ko/x/": {
            "url": "https://docs.nhncloud.com/ko/x/", "path": "Network/VPC/콘솔 사용 가이드.html",
            "breadcrumb": ["Network", "VPC", "콘솔 사용 가이드"], "fetched_at": "2026-09-17T00:00:00+00:00",
            "content_hash": "x", "image_count": 1, "status": "ok", "error": "",
        }
    }), encoding="utf-8")
    return str(tmp_path)


@pytest.fixture(scope="module")
def test_db():
    """실데이터 DB(ragdb)를 건드리지 않도록 ragdb_test 를 만들고 그쪽으로 연결을 돌린다."""
    import psycopg2
    import db

    admin = psycopg2.connect(host=db.DB_HOST, port=db.DB_PORT, database=db.DB_NAME,
                             user=db.DB_USER, password=db.DB_PASSWORD)
    admin.autocommit = True
    cur = admin.cursor()
    cur.execute("SELECT 1 FROM pg_database WHERE datname = 'ragdb_test'")
    if cur.fetchone() is None:
        cur.execute("CREATE DATABASE ragdb_test")
    cur.close()
    admin.close()

    original = db.DB_NAME
    db.DB_NAME = "ragdb_test"
    yield "ragdb_test"
    db.DB_NAME = original


@pytest.fixture
def conn(test_db):
    from db import get_conn
    c = get_conn()
    yield c
    c.close()


def test_uses_test_database(conn):
    cur = conn.cursor()
    cur.execute("SELECT current_database()")
    assert cur.fetchone()[0] == "ragdb_test"
    cur.close()


def rows(conn, source_path):
    cur = conn.cursor()
    cur.execute(
        "SELECT category, service, doc_type, doc_title, section_path, source_url, images "
        "FROM documents WHERE source_path = %s ORDER BY id",
        (source_path,),
    )
    out = cur.fetchall()
    cur.close()
    return out


def test_rebuild_then_skip_then_reingest_on_change(docs_dir, conn):
    import ingest

    assert ingest.run(["--docs-dir", docs_dir, "--rebuild"]) == 0
    got = rows(conn, "Network/VPC/콘솔 사용 가이드.html")
    assert len(got) == 2
    assert got[0][:4] == ("Network", "VPC", "console", "콘솔 사용 가이드")
    assert got[0][4] == "서브넷 생성"
    assert got[0][5] == "https://docs.nhncloud.com/ko/x/"
    assert got[0][6] == [{"path": "Network/VPC/images/s1.png", "caption": "서브넷 생성 버튼을 클릭합니다.", "alt": ""}]
    assert got[1][6] == []

    # 같은 내용이면 건너뛴다 (행 수 그대로)
    assert ingest.run(["--docs-dir", docs_dir]) == 0
    assert len(rows(conn, "Network/VPC/콘솔 사용 가이드.html")) == 2

    # 내용이 바뀌면 그 문서만 다시 적재한다
    path = os.path.join(docs_dir, "Network", "VPC", "콘솔 사용 가이드.html")
    with open(path, "a", encoding="utf-8") as f:
        f.write("<h3>추가</h3><p>추가 본문</p>")
    assert ingest.run(["--docs-dir", docs_dir]) == 0
    got = rows(conn, "Network/VPC/콘솔 사용 가이드.html")
    assert len(got) == 3
    assert got[2][4] == "추가"


def test_questions_table_exists(conn):
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM information_schema.tables WHERE table_name = 'questions'")
    assert cur.fetchone() is not None
    cur.close()
