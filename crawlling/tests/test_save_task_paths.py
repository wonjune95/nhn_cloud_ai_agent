"""save_task() 의 경로 충돌 방지(슬러그 접미사)와 no_breadcrumb 재크롤 방지를 검증한다.

Selenium 은 쓰지 않는다: fetch_section 을 monkeypatch 해 BeautifulSoup 섹션을 직접 돌려준다.
"""

import os

from bs4 import BeautifulSoup

from crawlling import crawl
from crawlling.manifest import Manifest


class DummyDriver:
    def quit(self):
        pass


def make_args(changed=False, force=False):
    ns = crawl.parse_args([])
    ns.changed = changed
    ns.force = force
    ns.sleep = 0
    return ns


def section_with_breadcrumb(breadcrumb: str) -> BeautifulSoup:
    html = f'<section><h2>{breadcrumb}</h2><p>본문</p></section>'
    return BeautifulSoup(html, "html.parser")


def section_without_breadcrumb(text: str = "제목만") -> BeautifulSoup:
    html = f'<section><h2>{text}</h2><p>본문</p></section>'
    return BeautifulSoup(html, "html.parser")


def stub_fetch_section(sections_by_url):
    def _fetch(driver, url, sleep):
        return sections_by_url[url]
    return _fetch


def test_second_url_with_same_breadcrumb_gets_slug_suffixed_path(tmp_path, monkeypatch):
    url_v2 = "https://docs.nhncloud.com/ko/Database/RDS%20for%20MySQL/ko/api-guide-v2.0/"
    url_v3 = "https://docs.nhncloud.com/ko/Database/RDS%20for%20MySQL/ko/api-guide-v3.0/"
    breadcrumb = "Database > RDS for MySQL > API 가이드"
    sections = {
        url_v2: section_with_breadcrumb(breadcrumb),
        url_v3: section_with_breadcrumb(breadcrumb),
    }
    monkeypatch.setattr(crawl, "fetch_section", stub_fetch_section(sections))
    monkeypatch.setattr(crawl, "download_images", lambda *a, **k: (0, 0))

    save_dir = str(tmp_path / "docs")
    manifest = Manifest.load(os.path.join(save_dir, "manifest.json"))
    args = make_args()

    task_v2 = {"category": "Database", "name": "API 가이드 v2.0", "url": url_v2}
    task_v3 = {"category": "Database", "name": "API 가이드 v3.0", "url": url_v3}

    result_v2 = crawl.save_task(task_v2, DummyDriver(), manifest, save_dir, args)
    result_v3 = crawl.save_task(task_v3, DummyDriver(), manifest, save_dir, args)

    assert result_v2 == "ok"
    assert result_v3 == "ok"

    entry_v2 = manifest.get(url_v2)
    entry_v3 = manifest.get(url_v3)
    assert entry_v2.path == "Database/RDS for MySQL/API 가이드.html"
    assert entry_v3.path == "Database/RDS for MySQL/API 가이드 (api-guide-v3.0).html"
    assert entry_v2.path != entry_v3.path

    assert os.path.exists(os.path.join(save_dir, entry_v2.path))
    assert os.path.exists(os.path.join(save_dir, entry_v3.path))

    paths = {e.path for e in manifest.entries.values()}
    assert len(paths) == 2


def test_no_breadcrumb_pages_use_url_service_to_avoid_collision(tmp_path, monkeypatch):
    url_a = "https://docs.nhncloud.com/ko/Security/Cloud%20Access/ko/overview/"
    url_b = "https://docs.nhncloud.com/ko/Security/Network-Firewall/ko/overview/"
    sections = {
        url_a: section_without_breadcrumb(),
        url_b: section_without_breadcrumb(),
    }
    monkeypatch.setattr(crawl, "fetch_section", stub_fetch_section(sections))
    monkeypatch.setattr(crawl, "download_images", lambda *a, **k: (0, 0))

    save_dir = str(tmp_path / "docs")
    manifest = Manifest.load(os.path.join(save_dir, "manifest.json"))
    args = make_args()

    task_a = {"category": "Security", "name": "개요", "url": url_a}
    task_b = {"category": "Security", "name": "개요", "url": url_b}

    crawl.save_task(task_a, DummyDriver(), manifest, save_dir, args)
    crawl.save_task(task_b, DummyDriver(), manifest, save_dir, args)

    entry_a = manifest.get(url_a)
    entry_b = manifest.get(url_b)
    assert entry_a.path == "Security/Cloud Access/개요.html"
    assert entry_b.path == "Security/Network-Firewall/개요.html"
    assert os.path.exists(os.path.join(save_dir, entry_a.path))
    assert os.path.exists(os.path.join(save_dir, entry_b.path))


def test_no_breadcrumb_entry_is_skipped_on_resume_without_force(tmp_path, monkeypatch):
    url = "https://docs.nhncloud.com/ko/Security/Cloud%20Access/ko/overview/"
    calls = {"n": 0}

    def counting_fetch(driver, u, sleep):
        calls["n"] += 1
        return section_without_breadcrumb()

    monkeypatch.setattr(crawl, "fetch_section", counting_fetch)
    monkeypatch.setattr(crawl, "download_images", lambda *a, **k: (0, 0))

    save_dir = str(tmp_path / "docs")
    manifest = Manifest.load(os.path.join(save_dir, "manifest.json"))
    args = make_args()
    task = {"category": "Security", "name": "개요", "url": url}

    first = crawl.save_task(task, DummyDriver(), manifest, save_dir, args)
    assert first == "no_breadcrumb"
    assert calls["n"] == 1

    second = crawl.save_task(task, DummyDriver(), manifest, save_dir, args)
    assert second == "skip"
    assert calls["n"] == 1


def test_recrawl_of_suffixed_url_with_force_keeps_same_suffixed_path(tmp_path, monkeypatch):
    url_v2 = "https://docs.nhncloud.com/ko/Database/RDS%20for%20MySQL/ko/api-guide-v2.0/"
    url_v3 = "https://docs.nhncloud.com/ko/Database/RDS%20for%20MySQL/ko/api-guide-v3.0/"
    breadcrumb = "Database > RDS for MySQL > API 가이드"
    sections = {
        url_v2: section_with_breadcrumb(breadcrumb),
        url_v3: section_with_breadcrumb(breadcrumb),
    }
    monkeypatch.setattr(crawl, "fetch_section", stub_fetch_section(sections))
    monkeypatch.setattr(crawl, "download_images", lambda *a, **k: (0, 0))

    save_dir = str(tmp_path / "docs")
    manifest = Manifest.load(os.path.join(save_dir, "manifest.json"))
    args = make_args()

    task_v2 = {"category": "Database", "name": "API 가이드 v2.0", "url": url_v2}
    task_v3 = {"category": "Database", "name": "API 가이드 v3.0", "url": url_v3}

    crawl.save_task(task_v2, DummyDriver(), manifest, save_dir, args)
    crawl.save_task(task_v3, DummyDriver(), manifest, save_dir, args)

    expected_path = "Database/RDS for MySQL/API 가이드 (api-guide-v3.0).html"
    assert manifest.get(url_v3).path == expected_path

    force_args = make_args(force=True)
    result = crawl.save_task(task_v3, DummyDriver(), manifest, save_dir, force_args)

    assert result == "ok"
    assert manifest.get(url_v3).path == expected_path
    assert os.path.exists(os.path.join(save_dir, expected_path))


def test_breadcrumb_change_moves_the_document_and_removes_the_old_copy(tmp_path, monkeypatch):
    """같은 URL 의 브레드크럼이 바뀌면 옛 파일과 옛 images/<문서명>/ 을 지운다."""
    url = "https://docs.nhncloud.com/ko/Compute/Instance/ko/console-guide/"
    state = {"crumb": "Compute > Instance > 콘솔 사용 가이드"}

    def fetch(driver, u, sleep):
        return section_with_breadcrumb(state["crumb"])

    def fake_download(section, doc_dir, page_url, doc_name, refresh=False):
        img_dir = os.path.join(doc_dir, "images", doc_name)
        os.makedirs(img_dir, exist_ok=True)
        with open(os.path.join(img_dir, "s1.png"), "wb") as f:
            f.write(b"png")
        return 1, 0

    monkeypatch.setattr(crawl, "fetch_section", fetch)
    monkeypatch.setattr(crawl, "download_images", fake_download)

    save_dir = str(tmp_path / "docs")
    manifest = Manifest.load(os.path.join(save_dir, "manifest.json"))
    task = {"category": "Compute", "name": "콘솔 사용 가이드", "url": url}

    crawl.save_task(task, DummyDriver(), manifest, save_dir, make_args())
    old_rel = manifest.get(url).path
    assert old_rel == "Compute/Instance/콘솔 사용 가이드.html"
    assert os.path.exists(os.path.join(save_dir, old_rel))
    old_images = os.path.join(save_dir, "Compute/Instance/images/콘솔 사용 가이드")
    assert os.path.isdir(old_images)

    # 브레드크럼이 바뀐 채 강제로 다시 저장한다.
    state["crumb"] = "Compute > Instance > 콘솔 사용 가이드 (신규)"
    crawl.save_task(task, DummyDriver(), manifest, save_dir, make_args(force=True))

    new_rel = manifest.get(url).path
    assert new_rel == "Compute/Instance/콘솔 사용 가이드 (신규).html"
    assert os.path.exists(os.path.join(save_dir, new_rel))
    assert not os.path.exists(os.path.join(save_dir, old_rel))       # 옛 파일이 남지 않는다
    assert not os.path.isdir(old_images)                             # 옛 이미지 폴더도 사라진다


def test_unchanged_path_is_not_deleted_on_recrawl(tmp_path, monkeypatch):
    """경로가 그대로면 아무것도 지우지 않는다 (덮어쓰기만)."""
    url = "https://docs.nhncloud.com/ko/Compute/Instance/ko/console-guide/"
    crumb = "Compute > Instance > 콘솔 사용 가이드"
    monkeypatch.setattr(crawl, "fetch_section", lambda d, u, s: section_with_breadcrumb(crumb))
    monkeypatch.setattr(crawl, "download_images", lambda *a, **k: (0, 0))

    save_dir = str(tmp_path / "docs")
    manifest = Manifest.load(os.path.join(save_dir, "manifest.json"))
    task = {"category": "Compute", "name": "콘솔 사용 가이드", "url": url}

    crawl.save_task(task, DummyDriver(), manifest, save_dir, make_args())
    crawl.save_task(task, DummyDriver(), manifest, save_dir, make_args(force=True))

    rel = manifest.get(url).path
    assert os.path.exists(os.path.join(save_dir, rel))
