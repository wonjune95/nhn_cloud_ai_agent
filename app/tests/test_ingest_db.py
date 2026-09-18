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
    assert got[0][6] == [{"path": "Network/VPC/images/s1.png", "caption": "서브넷 생성 버튼을 클릭합니다.",
                          "alt": "", "missing": False}]
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


def _insert_dummy_docs(conn, paths):
    """source_path 만 다른 최소 행. embedding 은 NULL 이어도 prune 판정에는 영향이 없다."""
    cur = conn.cursor()
    for i, path in enumerate(paths):
        cur.execute(
            """INSERT INTO documents
               (content, category, service, doc_type, doc_title, section_path, source_path, content_hash)
               VALUES (%s, 'Network', 'VPC', 'other', '더미', '절', %s, %s)""",
            (f"본문 {i}", path, f"h{i}"),
        )
    conn.commit()
    cur.close()


def _doc_count(conn):
    cur = conn.cursor()
    cur.execute("SELECT count(DISTINCT source_path) FROM documents")
    n = cur.fetchone()[0]
    cur.close()
    return n


def test_prune_refuses_to_delete_more_than_half(conn, monkeypatch, capsys):
    """정리 대상이 절반을 넘으면(그리고 PRUNE_MIN_ROWS 보다 많으면) 아무것도 지우지 않는다."""
    import db, ingest

    db.init_schema(conn, dim=8, rebuild=True)
    _insert_dummy_docs(conn, ["a", "b", "c", "d"])
    assert _doc_count(conn) == 4

    # 4건짜리 표로 '절반 초과' 만 보려고 최소 건수를 낮춘다 (운영 기본값은 10).
    monkeypatch.setattr(ingest, "PRUNE_MIN_ROWS", 2)

    assert ingest.prune_missing(conn, ["a"]) == 0           # 3/4 — 건너뛴다
    assert _doc_count(conn) == 4
    assert "절반 초과라 건너뜀" in capsys.readouterr().out

    assert ingest.prune_missing(conn, ["a", "b", "c"]) == 1  # 1/4 — 정상 정리
    assert _doc_count(conn) == 3


def test_prune_removes_rows_for_deleted_files(docs_dir, conn):
    import ingest, os

    assert ingest.run(["--docs-dir", docs_dir, "--rebuild"]) == 0
    # 두 번째 문서를 추가 적재한 뒤 파일을 지우면, 다음 전체 실행이 그 행을 정리한다
    extra = os.path.join(docs_dir, "Network", "VPC", "개요.html")
    with open(extra, "w", encoding="utf-8") as f:
        f.write("<section><h2>Network &gt; VPC &gt; 개요</h2><h3>소개</h3><p>VPC 개요 본문</p></section>")
    assert ingest.run(["--docs-dir", docs_dir]) == 0
    assert len(rows(conn, "Network/VPC/개요.html")) == 1

    os.remove(extra)
    assert ingest.run(["--docs-dir", docs_dir]) == 0
    assert rows(conn, "Network/VPC/개요.html") == []
    assert len(rows(conn, "Network/VPC/콘솔 사용 가이드.html")) == 2   # 남아 있는 문서는 그대로
