"""ingest.run() 의 종료 코드 (스펙 5-3). DB·API 없이 전부 가짜다."""
import json

import pytest

import ingest


HTML = "<section><h2>A &gt; B &gt; C</h2><h3>절</h3><p>본문</p></section>"


@pytest.fixture
def docs(tmp_path):
    (tmp_path / "A" / "B").mkdir(parents=True)
    (tmp_path / "A" / "B" / "C.html").write_text(HTML, encoding="utf-8")
    (tmp_path / "A" / "B" / "D.html").write_text(HTML, encoding="utf-8")
    (tmp_path / "manifest.json").write_text(json.dumps({}), encoding="utf-8")
    return str(tmp_path)


class FakeCursor:
    def execute(self, *a, **k): pass
    def fetchone(self): return None
    def fetchall(self): return []
    def close(self): pass


class FakeConn:
    def cursor(self): return FakeCursor()
    def commit(self): pass
    def rollback(self): pass
    def close(self): pass


def _fake_backend(monkeypatch, ingest_document):
    """가짜 백엔드를 깔고 prune_missing 호출 기록(seen 목록)을 돌려준다."""
    import db, llm
    monkeypatch.setattr(db, "get_conn", lambda: FakeConn())
    monkeypatch.setattr(db, "init_schema", lambda conn, dim, rebuild=False: None)
    monkeypatch.setattr(llm, "embed_one", lambda text, **k: [0.0] * 8)
    monkeypatch.setattr(ingest, "existing_hash", lambda cur, rel: None)

    prune_calls: list[list[str]] = []

    def spy(conn, seen):
        prune_calls.append(list(seen))
        return 0

    monkeypatch.setattr(ingest, "prune_missing", spy)
    monkeypatch.setattr(ingest, "ingest_document", ingest_document)
    return prune_calls


def test_partial_failure_exits_zero_and_lists_failures(docs, monkeypatch, capsys):
    def flaky(conn, docs_dir, rel, url, has_crumb):
        if rel.endswith("D.html"):
            raise RuntimeError("임베딩 429")
        return 3
    _fake_backend(monkeypatch, flaky)

    assert ingest.run(["--docs-dir", docs]) == 0
    out = capsys.readouterr().out
    assert "1개 실패" in out and "D.html" in out and "RuntimeError: 임베딩 429" in out


def test_all_ok_exits_zero(docs, monkeypatch):
    _fake_backend(monkeypatch, lambda *a: 2)
    assert ingest.run(["--docs-dir", docs]) == 0


def test_no_documents_exits_one(tmp_path, monkeypatch, capsys):
    """HTML 이 한 건도 없으면 정리를 건드리기 전에 멈춘다 — 빈 폴더로 인덱스가 날아가면 안 된다."""
    (tmp_path / "manifest.json").write_text("{}", encoding="utf-8")
    prune_calls = _fake_backend(monkeypatch, lambda *a: 1)
    assert ingest.run(["--docs-dir", str(tmp_path)]) == 1
    assert "처리할 문서가 없습니다" in capsys.readouterr().out
    assert prune_calls == []


def test_partial_failure_still_prunes(docs, monkeypatch):
    """한 문서가 실패해도 정리는 돈다 — 실패 문서도 seen 에 있어야 행이 살아남는다."""
    def flaky(conn, docs_dir, rel, url, has_crumb):
        if rel.endswith("D.html"):
            raise RuntimeError("임베딩 429")
        return 3
    prune_calls = _fake_backend(monkeypatch, flaky)

    assert ingest.run(["--docs-dir", docs]) == 0
    assert len(prune_calls) == 1
    assert sorted(prune_calls[0]) == ["A/B/C.html", "A/B/D.html"]


def test_db_connection_failure_exits_one(docs, monkeypatch, capsys):
    import db, llm
    monkeypatch.setattr(llm, "embed_one", lambda text, **k: [0.0] * 8)

    def boom():
        raise OSError("connection refused")
    monkeypatch.setattr(db, "get_conn", boom)

    assert ingest.run(["--docs-dir", docs]) == 1
    assert "DB 연결 실패" in capsys.readouterr().out


def test_embedding_auth_failure_exits_one(docs, monkeypatch, capsys):
    import db, llm
    monkeypatch.setattr(db, "get_conn", lambda: FakeConn())

    def boom(text, **k):
        raise RuntimeError("NVIDIA_API_KEY 가 설정되지 않았습니다")
    monkeypatch.setattr(llm, "embed_one", boom)

    assert ingest.run(["--docs-dir", docs]) == 1
    assert "임베딩 API 실패" in capsys.readouterr().out


def test_missing_manifest_still_exits_one(tmp_path):
    (tmp_path / "x.html").write_text(HTML, encoding="utf-8")
    assert ingest.run(["--docs-dir", str(tmp_path)]) == 1
