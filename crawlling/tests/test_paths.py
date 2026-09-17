import pytest

from crawlling.paths import (
    clean_name,
    disambiguate,
    doc_path,
    extract_breadcrumb,
    fallback_path,
    parse_breadcrumb,
    url_service,
    url_slug,
)


def test_clean_name_replaces_forbidden_chars_and_strips():
    assert clean_name(' API v1.0: 가이드? ') == 'API v1.0_ 가이드_'


def test_parse_breadcrumb_strips_and_drops_empty():
    text = " Compute >  Virtual Desktop > 콘솔 사용 가이드 "
    assert parse_breadcrumb(text) == ["Compute", "Virtual Desktop", "콘솔 사용 가이드"]


def test_doc_path_three_levels():
    parts = ["Compute", "Virtual Desktop", "콘솔 사용 가이드"]
    assert doc_path(parts) == "Compute/Virtual Desktop/콘솔 사용 가이드.html"


def test_doc_path_two_levels_uses_placeholder_service():
    assert doc_path(["Bill", "서비스 가이드"]) == "Bill/_/서비스 가이드.html"


def test_doc_path_four_levels_joins_middle_as_service():
    parts = ["Game", "Gamebase", "Console", "가이드"]
    assert doc_path(parts) == "Game/Gamebase - Console/가이드.html"


def test_doc_path_cleans_each_part():
    assert doc_path(["A/B", "C:D", "E?"]) == "A_B/C_D/E_.html"


def test_doc_path_rejects_single_level():
    with pytest.raises(ValueError):
        doc_path(["Compute"])


def test_extract_breadcrumb_from_first_h2():
    html = (
        '<section><h2 id="x">\n Compute &gt; Virtual Desktop &gt; 콘솔 사용 가이드\n</h2>'
        "<h2>다른 제목</h2></section>"
    )
    assert extract_breadcrumb(html) == ["Compute", "Virtual Desktop", "콘솔 사용 가이드"]


def test_extract_breadcrumb_returns_none_without_separator():
    assert extract_breadcrumb("<section><h2>제목만</h2></section>") is None


def test_extract_breadcrumb_returns_none_without_h2():
    assert extract_breadcrumb("<section><p>본문</p></section>") is None


def test_fallback_path():
    assert fallback_path("Compute", "콘솔 사용 가이드") == "Compute/_/콘솔 사용 가이드.html"


def test_fallback_path_with_service_uses_it_instead_of_placeholder():
    assert fallback_path("Security", "개요", service="Cloud Access") == "Security/Cloud Access/개요.html"


def test_url_service_extracts_and_decodes_service_segment():
    url = "https://docs.nhncloud.com/ko/Security/Cloud%20Access/ko/overview/"
    assert url_service(url) == "Cloud Access"


def test_url_service_none_for_non_service_shape_public_api():
    url = "https://docs.nhncloud.com/ko/nhncloud/ko/public-api/service-api/"
    assert url_service(url) is None


def test_url_service_none_for_non_service_shape_quickstarts():
    url = "https://docs.nhncloud.com/ko/quickstarts/ko/overview/"
    assert url_service(url) is None


def test_url_slug_is_last_path_segment_decoded():
    url = "https://docs.nhncloud.com/ko/Database/RDS%20for%20MySQL/ko/api-guide-v3.0/"
    assert url_slug(url) == "api-guide-v3.0"


def test_url_slug_defaults_to_index_for_root():
    assert url_slug("https://docs.nhncloud.com/") == "index"


def test_disambiguate_inserts_slug_before_extension():
    rel = "Database/RDS for MySQL/API 가이드.html"
    assert disambiguate(rel, "api-guide-v3.0") == "Database/RDS for MySQL/API 가이드 (api-guide-v3.0).html"
