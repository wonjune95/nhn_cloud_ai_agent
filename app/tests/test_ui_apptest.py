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
