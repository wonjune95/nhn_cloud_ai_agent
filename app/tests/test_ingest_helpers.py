import ingest
from ingest import doc_type_of, split_source_path


def test_doc_type_console():
    assert doc_type_of("콘솔 사용 가이드") == "console"
    assert doc_type_of("Amazon 콘솔 가이드") == "console"


def test_doc_type_api():
    assert doc_type_of("API v3.0 가이드") == "api"
    assert doc_type_of("Open API 개요") == "api"      # API 가 개요보다 우선


def test_doc_type_overview():
    assert doc_type_of("개요") == "overview"


def test_doc_type_other():
    assert doc_type_of("릴리스 노트") == "other"
    assert doc_type_of("Terraform 사용 가이드") == "other"


def test_split_source_path_three_levels():
    assert split_source_path("Network/VPC/콘솔 사용 가이드.html") == ("Network", "VPC", "콘솔 사용 가이드")


def test_split_source_path_placeholder_service():
    assert split_source_path("Bill/_/서비스 가이드.html") == ("Bill", "_", "서비스 가이드")


def test_split_source_path_two_levels_becomes_placeholder():
    assert split_source_path("Bill/서비스 가이드.html") == ("Bill", "_", "서비스 가이드")


def test_split_source_path_accepts_backslashes():
    assert split_source_path("Network\\VPC\\API 가이드.html") == ("Network", "VPC", "API 가이드")


def test_run_refuses_docs_dir_without_manifest(tmp_path, capsys):
    (tmp_path / "문서.html").write_text("<section><h3>A</h3><p>본문</p></section>", encoding="utf-8")

    # manifest.json 이 없으므로 DB/임베딩 API 에 닿기 전에 거절해야 한다.
    assert ingest.run(["--docs-dir", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "manifest.json" in out
    assert "--allow-no-manifest" in out


def test_load_manifest_gives_url_and_breadcrumb_flag(tmp_path):
    import json
    from ingest import load_manifest
    (tmp_path / "manifest.json").write_text(json.dumps({
        "https://d/a": {"path": "A/B/c.html", "url": "https://d/a", "breadcrumb": ["A", "B", "c"], "status": "ok"},
        "https://d/b": {"path": "A/_/d.html", "url": "https://d/b", "breadcrumb": [], "status": "no_breadcrumb"},
    }), encoding="utf-8")
    m = load_manifest(str(tmp_path))
    assert m["A/B/c.html"] == ("https://d/a", True)
    assert m["A/_/d.html"] == ("https://d/b", False)
    assert load_manifest(str(tmp_path / "없음")) == {}
