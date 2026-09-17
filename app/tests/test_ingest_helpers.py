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
