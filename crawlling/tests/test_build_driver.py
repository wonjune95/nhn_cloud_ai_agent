"""build_driver() 가 컨테이너(CHROME_BIN/CHROMEDRIVER)와 로컬(webdriver-manager)을 구분하는지 검증한다.
실제 브라우저는 띄우지 않는다 — webdriver.Chrome 과 ChromeDriverManager 를 가짜로 바꾼다."""

from crawlling import crawl


class FakeChrome:
    def __init__(self, service=None, options=None):
        self.service = service
        self.options = options


class FakeService:
    def __init__(self, path=None):
        self.path = path


class FakeManager:
    called = False

    def install(self):
        FakeManager.called = True
        return "/managed/chromedriver"


def _patch(monkeypatch):
    FakeManager.called = False
    monkeypatch.setattr(crawl.webdriver, "Chrome", FakeChrome)
    monkeypatch.setattr(crawl, "Service", FakeService)
    monkeypatch.setattr(crawl, "ChromeDriverManager", FakeManager)


def test_uses_env_binaries_when_set(monkeypatch):
    _patch(monkeypatch)
    monkeypatch.setenv("CHROME_BIN", "/usr/bin/chromium")
    monkeypatch.setenv("CHROMEDRIVER", "/usr/bin/chromedriver")

    d = crawl.build_driver()

    assert d.service.path == "/usr/bin/chromedriver"
    assert d.options.binary_location == "/usr/bin/chromium"
    assert FakeManager.called is False
    assert "--headless=new" in d.options.arguments and "--no-sandbox" in d.options.arguments


def test_falls_back_to_webdriver_manager(monkeypatch):
    _patch(monkeypatch)
    monkeypatch.delenv("CHROME_BIN", raising=False)
    monkeypatch.delenv("CHROMEDRIVER", raising=False)

    d = crawl.build_driver()

    assert d.service.path == "/managed/chromedriver"
    assert FakeManager.called is True
    assert not d.options.binary_location


def test_both_env_vars_required_for_container_mode(monkeypatch):
    """둘 중 하나만 있으면 로컬 모드로 본다 — 반쯤 설정된 컨테이너에서 엉뚱한 드라이버를 쓰지 않게."""
    _patch(monkeypatch)
    monkeypatch.setenv("CHROME_BIN", "/usr/bin/chromium")
    monkeypatch.delenv("CHROMEDRIVER", raising=False)

    d = crawl.build_driver()

    assert d.service.path == "/managed/chromedriver"
