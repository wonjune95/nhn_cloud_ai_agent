"""download_images() 의 문서별 이미지 폴더 분리, 새로고침, 실패 처리를 검증한다."""

import hashlib

from bs4 import BeautifulSoup

from crawlling import crawl

PAGE_URL = "https://docs.nhncloud.com/ko/x/"
BAD_URL = "https://docs.nhncloud.com/img/bad.png"


class FakeResponse:
    def __init__(self, content: bytes = b"PNGDATA"):
        self.status_code = 200
        self.content = content

    def raise_for_status(self):
        pass


def fake_get(url, timeout=None):
    if url == BAD_URL:
        raise RuntimeError("network error")
    return FakeResponse()


def section_from(html: str):
    return BeautifulSoup(html, "html.parser")


def test_rewrite_and_save_two_images(tmp_path, monkeypatch):
    monkeypatch.setattr(crawl.requests, "get", fake_get)
    html = '<section><img src="./images/a.png"><img src="./images/b.png"></section>'
    section = section_from(html)

    ok, missing = crawl.download_images(section, str(tmp_path), PAGE_URL, "doc1")

    assert (ok, missing) == (2, 0)
    assert (tmp_path / "images" / "doc1" / "a.png").exists()
    assert (tmp_path / "images" / "doc1" / "b.png").exists()
    imgs = section.find_all("img")
    assert imgs[0]["src"] == "./images/doc1/a.png"
    assert imgs[1]["src"] == "./images/doc1/b.png"


def test_same_basename_different_url_gets_hash_prefix(tmp_path, monkeypatch):
    monkeypatch.setattr(crawl.requests, "get", fake_get)
    html = ('<section><img src="https://cdn1.example.com/x/a.png">'
            '<img src="https://cdn2.example.com/y/a.png"></section>')
    section = section_from(html)

    ok, missing = crawl.download_images(section, str(tmp_path), PAGE_URL, "doc1")

    assert (ok, missing) == (2, 0)
    second_url = "https://cdn2.example.com/y/a.png"
    prefix = hashlib.sha1(second_url.encode("utf-8")).hexdigest()[:8]
    imgs = section.find_all("img")
    assert imgs[0]["src"] == "./images/doc1/a.png"
    assert imgs[1]["src"] == f"./images/doc1/{prefix}_a.png"
    assert (tmp_path / "images" / "doc1" / "a.png").exists()
    assert (tmp_path / "images" / "doc1" / f"{prefix}_a.png").exists()


def test_download_failure_keeps_absolute_url_and_marks_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(crawl.requests, "get", fake_get)
    html = f'<section><img src="{BAD_URL}"></section>'
    section = section_from(html)

    ok, missing = crawl.download_images(section, str(tmp_path), PAGE_URL, "doc1")

    assert (ok, missing) == (0, 1)
    img = section.find("img")
    assert img["src"] == BAD_URL
    assert img["data-missing"] == "true"
    assert not (tmp_path / "images" / "doc1" / "bad.png").exists()
    # 이미지가 하나도 저장되지 못했으면 images/ 폴더 자체가 생기지 않는다.
    assert not (tmp_path / "images").exists()


def test_existing_file_skipped_without_refresh_and_refetched_with_refresh(tmp_path, monkeypatch):
    calls: list[str] = []

    def counting_get(url, timeout=None):
        calls.append(url)
        return FakeResponse()

    monkeypatch.setattr(crawl.requests, "get", counting_get)

    doc_dir = str(tmp_path)
    img_dir = tmp_path / "images" / "doc1"
    img_dir.mkdir(parents=True)
    (img_dir / "a.png").write_bytes(b"OLD")

    html = '<section><img src="./images/a.png"></section>'

    ok, missing = crawl.download_images(section_from(html), doc_dir, PAGE_URL, "doc1", refresh=False)
    assert (ok, missing) == (1, 0)
    assert calls == []
    assert (img_dir / "a.png").read_bytes() == b"OLD"

    ok, missing = crawl.download_images(section_from(html), doc_dir, PAGE_URL, "doc1", refresh=True)
    assert (ok, missing) == (1, 0)
    assert len(calls) == 1
    assert (img_dir / "a.png").read_bytes() == b"PNGDATA"
