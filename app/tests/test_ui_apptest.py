"""Streamlit AppTest 로 챗 화면 배선을 검사한다. DB·LLM 은 전부 가짜다."""
import pathlib
import types

import pytest
from streamlit.testing.v1 import AppTest

import rag
from rag import Candidate, ImageRef

# AppTest.from_file 은 상대 경로를 "호출한 파일" 기준으로 푼다 (여기는 app/tests).
# 저장소 루트 기준의 app/ui.py 를 절대 경로로 넘겨야 한다.
UI_PATH = str(pathlib.Path(__file__).resolve().parents[1] / "ui.py")

# 1x1 투명 PNG. 여러 테스트가 스크린샷 파일로 재사용한다.
PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
    b"\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


def fake_index(monkeypatch, calls):
    """rag 의 무거운 부분을 가짜로 바꾼다. calls 에 검색 인자와 피드백 호출을 기록한다."""
    import chat_page
    import qlog
    import db

    c = Candidate(content="본문", source_path="Network/VPC/콘솔 사용 가이드.html", service="Network/VPC",
                  doc_type="console", score=1.0, section_path="서브넷 생성", source_url="https://x/",
                  images=[{"path": "Network/VPC/images/a.png", "caption": "캡", "alt": "", "missing": False}])

    monkeypatch.setattr(rag, "build_bm25", lambda: 3)
    monkeypatch.setattr(rag, "ALIASES", {"vpc": "Network/VPC", "오브젝트": "Storage/Object Storage"})
    monkeypatch.setattr(db, "migrate", lambda conn: None)
    monkeypatch.setattr(db, "get_conn", lambda: types.SimpleNamespace(close=lambda: None))

    def hybrid(query, intent="general", service=None, top_k=20):
        calls.append(("search", query, intent, service))
        return [c]

    def rerank(query, cands, top_k=5):
        return cands, True

    def stream(question, cands, history=None, intent="general"):
        calls.append(("answer", intent))
        return iter(["콘솔 > Network > VPC\n1. 클릭 {{img:1}}"]), {1: ImageRef("Network/VPC/images/a.png", "캡")}

    monkeypatch.setattr(rag, "hybrid_search", hybrid)
    monkeypatch.setattr(rag, "rerank_candidates", rerank)
    monkeypatch.setattr(rag, "answer_stream", stream)
    monkeypatch.setattr(qlog, "log_question", lambda **kw: calls.append(("log", kw)) or 42)
    monkeypatch.setattr(qlog, "set_feedback", lambda qid, v: calls.append(("feedback", qid, v)) or True)
    chat_page.load_index.clear()


@pytest.fixture
def app(monkeypatch):
    calls = []
    fake_index(monkeypatch, calls)
    at = AppTest.from_file(UI_PATH, default_timeout=30)
    return at, calls


def test_service_dropdown_overrides_detection_and_answer_is_logged(app):
    at, calls = app
    at.run()
    assert not at.exception

    at.sidebar.selectbox[0].select("Storage/Object Storage")
    at.chat_input[0].set_value("서브넷 만드는 법").run()
    assert not at.exception

    search = next(c for c in calls if c[0] == "search")
    assert search[3] == "Storage/Object Storage"
    log = next(c for c in calls if c[0] == "log")[1]
    assert log["question"] == "서브넷 만드는 법" and log["service"] == "Storage/Object Storage"
    assert log["grounded"] is True and log["session_id"]
    assert log["sources"][0]["source_url"] == "https://x/"
    # 마커가 화면에 그대로 남지 않는다 (치환됨).
    assert all("{{img:" not in m.value for m in at.markdown)


def test_thumbs_down_saves_feedback(app):
    at, calls = app
    at.run()
    at.chat_input[0].set_value("서브넷 만드는 법").run()
    down = next(b for b in at.button if b.label == "👎")
    down.click().run()
    assert ("feedback", 42, -1) in calls
    assert any("의견 감사합니다" in c.value for c in at.caption)


def test_not_grounded_skips_llm(app, monkeypatch):
    at, calls = app
    monkeypatch.setattr(rag, "rerank_candidates", lambda q, cands, top_k=5: (cands, False))
    at.run()
    at.chat_input[0].set_value("전혀 없는 질문").run()
    assert not any(c[0] == "answer" for c in calls)
    assert any("제공된 문서에서 확인되지 않습니다" in m.value for m in at.markdown)
    log = next(c for c in calls if c[0] == "log")[1]
    assert log["grounded"] is False
    # 근거가 없으면 출처를 보여 주지도, 로그에 남기지도 않는다.
    assert log["sources"] == []
    assert not any("참고한 문서" in e.label for e in at.expander)


def test_markers_become_images(app, monkeypatch, tmp_path):
    """{{img:N}} 이 실제 파일을 가리키면 st.image 로 그린다 (스펙 3-4)."""
    import chat_page

    png = tmp_path / "Network" / "VPC" / "images"
    png.mkdir(parents=True)
    (png / "a.png").write_bytes(PNG_1X1)
    monkeypatch.setattr(chat_page, "DOCS_DIR", str(tmp_path))

    at, _calls = app
    at.run()
    at.chat_input[0].set_value("서브넷 만드는 법").run()
    assert not at.exception

    assert len(at.image) >= 1
    assert any("캡" in c for img in at.image for c in img.captions)
    assert all("{{img:" not in m.value for m in at.markdown)


def test_sibling_images_are_borrowed_and_rendered(app, monkeypatch, tmp_path):
    """이미지가 없는 후보도 같은 문서·같은 최상위 섹션의 이웃 청크 스크린샷을 빌려 화면에 그린다.

    rag.enrich_images → rag.build_prompt(번호 매기기) → chat_page.render_answer 까지의 배선을 본다.
    """
    import chat_page
    from dataclasses import replace

    png = tmp_path / "Network" / "VPC" / "images"
    png.mkdir(parents=True)
    (png / "sib.png").write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
        b"\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    monkeypatch.setattr(chat_page, "DOCS_DIR", str(tmp_path))

    target = Candidate(content="절차 본문", source_path="Network/VPC/콘솔 사용 가이드.html",
                       service="Network/VPC", doc_type="console", score=1.0,
                       section_path="서브넷 생성 > 3단계", source_url="https://x/", images=[])
    sibling = replace(target, content="이웃 본문", section_path="서브넷 생성 > 2단계",
                      images=[{"path": "Network/VPC/images/sib.png", "caption": "이웃 캡",
                               "alt": "", "missing": False}])
    monkeypatch.setattr(rag, "bm25_meta", [sibling])
    monkeypatch.setattr(rag, "hybrid_search", lambda q, intent="general", service=None, top_k=20: [target])

    def stream(question, cands, history=None, intent="general"):
        # 순번표는 진짜 build_prompt 로 만든다 — 빌려온 이미지가 번호를 받는지까지 확인한다.
        _prompt, image_map = rag.build_prompt(question, cands, history, intent=intent)
        return iter(["단계 {{img:1}}"]), image_map

    monkeypatch.setattr(rag, "answer_stream", stream)

    at, _calls = app
    at.run()
    at.chat_input[0].set_value("서브넷 만드는 법").run()
    assert not at.exception

    assert len(at.image) >= 1
    assert any("이웃 캡" in c for img in at.image for c in img.captions)
    assert all("{{img:" not in m.value for m in at.markdown)


def test_traversal_image_path_is_skipped(app, monkeypatch, tmp_path):
    """DOCS_DIR 밖을 가리키는 이미지 경로(../..)는 그 그림만 건너뛰고 트레이스백도 없다."""
    import chat_page

    png = tmp_path / "Network" / "VPC" / "images"
    png.mkdir(parents=True)
    (png / "a.png").write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
        b"\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    monkeypatch.setattr(chat_page, "DOCS_DIR", str(tmp_path))

    def stream(question, cands, history=None, intent="general"):
        text = "콘솔 > Network > VPC\n1. 클릭 {{img:1}}\n2. 벗어남 {{img:2}}"
        image_map = {
            1: rag.ImageRef("Network/VPC/images/a.png", "캡"),
            2: rag.ImageRef("../../etc/passwd", "탈출 시도"),
        }
        return iter([text]), image_map

    monkeypatch.setattr(rag, "answer_stream", stream)

    at, _calls = app
    at.run()
    at.chat_input[0].set_value("서브넷 만드는 법").run()
    assert not at.exception

    assert len(at.image) == 1
    assert all("{{img:" not in m.value for m in at.markdown)


def test_answer_failure_is_shown_and_logged(app, monkeypatch):
    """모델 호출이 터져도 화면은 살아 있고, 오류가 로그에 남는다."""
    def boom(question, cands, history=None, intent="general"):
        raise RuntimeError("503")

    at, calls = app
    monkeypatch.setattr(rag, "answer_stream", boom)
    at.run()
    at.chat_input[0].set_value("서브넷 만드는 법").run()
    assert not at.exception

    assert any("모델 서버가 일시적으로 혼잡해" in m.value for m in at.markdown)
    log = next(c for c in calls if c[0] == "log")[1]
    assert "503" in log["error"]
    # 검색은 성공했으니 cands 는 살려 두고 로그(sources)에 남긴다 — 화면에는 안 보인다 (render_sources 미호출).
    assert log["sources"] == [{
        "source_path": "Network/VPC/콘솔 사용 가이드.html", "section_path": "서브넷 생성",
        "source_url": "https://x/", "service": "Network/VPC",
    }]

    # 기록을 다시 그릴 때(rerun)도 실패한 턴은 cands 를 갖고 있지만 출처를 보이면 안 된다.
    at.run()
    assert not at.exception
    assert not any("참고한 문서" in e.label for e in at.expander)


def test_feedback_buttons_show_caption_when_question_id_is_none(app, monkeypatch):
    """로그 저장이 실패(question_id 없음)하면 버튼 대신 안내 문구만 보인다 (스펙 6절)."""
    import qlog

    at, calls = app
    monkeypatch.setattr(qlog, "log_question", lambda **kw: calls.append(("log", kw)) or None)
    at.run()
    at.chat_input[0].set_value("서브넷 만드는 법").run()
    assert not at.exception

    assert any("저장 실패" in c.value for c in at.caption)
    assert not any(b.label == "👍" for b in at.button)


def test_reset_clears_feedback_state(app):
    """'대화 초기화' 는 fb_* 상태까지 지운다 (순번 재사용으로 남의 평가를 물려받지 않게)."""
    at, calls = app
    at.run()
    at.chat_input[0].set_value("서브넷 만드는 법").run()
    next(b for b in at.button if b.label == "👎").click().run()
    assert any("의견 감사합니다" in c.value for c in at.caption)

    next(b for b in at.button if b.label == "대화 초기화").click().run()
    assert not at.exception
    assert not at.session_state.messages
    assert "fb_q42" not in at.session_state
    assert not any("의견 감사합니다" in c.value for c in at.caption)


def test_admin_page_renders_metrics_with_fake_stats(monkeypatch):
    import admin_stats as s
    import admin_page
    import schema_ready

    monkeypatch.setattr(schema_ready, "ensure_schema", lambda: None)
    monkeypatch.setattr(admin_page, "get_conn", lambda: types.SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(s, "summary", lambda conn, since: {
        "questions": 12, "sessions": 4, "median_s": 9.5, "max_s": 31.0,
        "error_rate": 0.25, "ungrounded_rate": 0.5, "up": 3, "down": 2})
    monkeypatch.setattr(s, "by_service", lambda conn, since: [("Network/VPC", 5, 2, 1)])
    monkeypatch.setattr(s, "recent_down", lambda conn, since, limit=20: [])
    monkeypatch.setattr(s, "recent_ungrounded", lambda conn, since, limit=20: [])
    monkeypatch.setattr(s, "recent_slow", lambda conn, since, limit=20, threshold_ms=30000: [])
    monkeypatch.setattr(s, "index_status", lambda conn: {"chunks": 100, "services": 7, "last_ingested_at": None})

    at = AppTest.from_string("import admin_page\nadmin_page.page()\n", default_timeout=30)
    at.run()
    assert not at.exception
    assert any(m.value == "12" for m in at.metric)
    assert any("25%" in m.value for m in at.metric)
    assert any("Network/VPC" in str(d.value) for d in at.dataframe)


def test_admin_page_shows_banner_when_schema_not_migrated(monkeypatch):
    """2B 컬럼이 아직 없는 DB(UndefinedColumn)에서도 트레이스백 없이 배너만 뜬다."""
    import admin_stats as s
    import admin_page
    import schema_ready

    monkeypatch.setattr(schema_ready, "ensure_schema", lambda: None)
    monkeypatch.setattr(admin_page, "get_conn", lambda: types.SimpleNamespace(close=lambda: None))

    def boom(conn, since):
        raise RuntimeError("UndefinedColumn")

    monkeypatch.setattr(s, "summary", boom)

    at = AppTest.from_string("import admin_page\nadmin_page.page()\n", default_timeout=30)
    at.run()
    assert not at.exception
    assert any("DB 에서 지표를 읽지 못했습니다" in e.value for e in at.error)
    assert any("UndefinedColumn" in c.value for c in at.caption)


def _fake_admin_stats(monkeypatch):
    """토큰 게이트 테스트에서는 통과 후 화면이 정상 렌더되는지만 보면 되므로 최소한만 가짜로 만든다."""
    import admin_stats as s
    import admin_page
    import schema_ready

    monkeypatch.setattr(schema_ready, "ensure_schema", lambda: None)
    monkeypatch.setattr(admin_page, "get_conn", lambda: types.SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(s, "summary", lambda conn, since: {
        "questions": 12, "sessions": 4, "median_s": 9.5, "max_s": 31.0,
        "error_rate": 0.25, "ungrounded_rate": 0.5, "up": 3, "down": 2})
    monkeypatch.setattr(s, "by_service", lambda conn, since: [("Network/VPC", 5, 2, 1)])
    monkeypatch.setattr(s, "recent_down", lambda conn, since, limit=20: [])
    monkeypatch.setattr(s, "recent_ungrounded", lambda conn, since, limit=20: [])
    monkeypatch.setattr(s, "recent_slow", lambda conn, since, limit=20, threshold_ms=30000: [])
    monkeypatch.setattr(s, "index_status", lambda conn: {"chunks": 100, "services": 7, "last_ingested_at": None})


def test_admin_page_open_when_admin_token_is_empty(monkeypatch):
    """ADMIN_TOKEN 이 비어 있으면(로컬 개발) 게이트 없이 바로 지표가 보인다."""
    import admin_auth

    _fake_admin_stats(monkeypatch)
    monkeypatch.setattr(admin_auth, "required_token", lambda: "")

    at = AppTest.from_string("import admin_page\nadmin_page.page()\n", default_timeout=30)
    at.run()
    assert not at.exception
    assert any(m.value == "12" for m in at.metric)


def test_admin_page_requires_token_when_admin_token_is_set(monkeypatch):
    """ADMIN_TOKEN 이 설정돼 있으면 토큰 입력창이 뜨고, 맞는 토큰을 넣어야만 지표가 보인다."""
    import admin_auth

    _fake_admin_stats(monkeypatch)
    monkeypatch.setattr(admin_auth, "required_token", lambda: "s3cret")

    at = AppTest.from_string("import admin_page\nadmin_page.page()\n", default_timeout=30)
    at.run()
    assert not at.exception
    assert at.text_input
    assert not at.metric

    # 틀린 토큰: 오류만 뜨고 여전히 지표는 없다.
    at.text_input[0].input("wrong").run()
    at.button[0].click().run()
    assert not at.exception
    assert any("토큰이 올바르지 않습니다" in e.value for e in at.error)
    assert not at.metric

    # 맞는 토큰: 세션에 저장되고 rerun 후 지표가 보인다.
    at.text_input[0].input("s3cret").run()
    at.button[0].click().run()
    assert not at.exception
    at.run()
    assert any(m.value == "12" for m in at.metric)


def test_source_card_html_numbers_and_links():
    import chat_page
    from rag import Candidate
    c = Candidate(content="본문", source_path="Network/DNS Plus/콘솔 사용 가이드.html", service="Network/DNS Plus",
                  doc_type="console", score=1.0, section_path="레코드 세트 관리 > 레코드 세트 생성",
                  source_url="https://docs.nhncloud.com/ko/x/")
    html = chat_page.source_card_html(2, c)
    assert "[2]" in html and "콘솔 사용 가이드" in html and "Network/DNS Plus" in html
    assert "레코드 세트 관리 › 레코드 세트 생성" in html
    assert 'href="https://docs.nhncloud.com/ko/x/"' in html and "원문" in html


def test_source_card_without_url_has_no_link():
    import chat_page
    from rag import Candidate
    c = Candidate(content="본문", source_path="A/B/C.html", service="A/B", doc_type="other", score=0.0)
    html = chat_page.source_card_html(1, c)
    assert "href=" not in html and "[1]" in html


def test_sources_render_as_cards_not_expander(app):
    at, _ = app
    at.run()
    at.chat_input[0].set_value("서브넷 만드는 법").run()
    assert not any("참고한 문서" in e.label for e in at.expander)
    assert any("[1]" in m.value and "nhn-cite-card" in m.value for m in at.markdown)


def test_source_card_html_escapes_corpus_values():
    import chat_page
    from rag import Candidate
    c = Candidate(content="본문", source_path='a<b>"c.html', service="A/B", doc_type="other", score=0.0,
                  section_path="x > <script>", source_url='https://x/?a="b"')
    html_out = chat_page.source_card_html(1, c)
    assert "<script>" not in html_out
    assert "&quot;" in html_out
    assert "[1]" in html_out


def test_status_shows_candidate_chips(app):
    at, _ = app
    at.run()
    at.chat_input[0].set_value("서브넷 만드는 법").run()
    status_texts = [m.value for m in at.markdown if "nhn-progress-chip" in m.value]
    assert status_texts, "status 안에 후보 칩이 없다"
    assert any("콘솔 사용 가이드" in t and "서브넷 생성" in t for t in status_texts)


def test_candidate_chip_text():
    import chat_page
    from rag import Candidate
    c = Candidate(content="", source_path="Network/VPC/콘솔 사용 가이드.html", service="Network/VPC",
                  doc_type="console", score=0.0, section_path="서브넷 > 서브넷 생성")
    assert chat_page.candidate_chip(c) == "Network/VPC · 콘솔 사용 가이드 › 서브넷 › 서브넷 생성"


def test_zoom_button_exists_and_opens_without_error(app, monkeypatch, tmp_path):
    at, _ = app
    import chat_page
    img_dir = tmp_path / "Network" / "VPC" / "images"
    img_dir.mkdir(parents=True)
    (img_dir / "a.png").write_bytes(PNG_1X1)
    monkeypatch.setattr(chat_page, "DOCS_DIR", str(tmp_path))
    at.run()
    at.chat_input[0].set_value("서브넷 만드는 법").run()
    zoom = [b for b in at.button if b.label == "크게 보기"]
    assert zoom, "크게 보기 버튼이 없다"
    zoom[0].click().run()
    assert not at.exception


def test_zoom_key_is_stable_per_question_and_image():
    import chat_page
    assert chat_page.zoom_key(42, 1, 0) == "zoom_q42_1"
    assert chat_page.zoom_key(42, 1, 7) == "zoom_s7_1"
    assert chat_page.zoom_key(None, 2, 0) == "zoom_x_2"
