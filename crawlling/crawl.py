"""docs.nhncloud.com 문서 수집기.

메뉴(GNB)에서 모든 문서 링크를 모은 뒤, 페이지 본문(section.page__content-wrapper)만
'카테고리/서비스/문서명.html' 로 저장한다. 경로는 본문 첫 <h2>의 브레드크럼으로 정한다.
이미지는 같은 폴더의 images/<문서명>/ 에 원본 파일명으로 받고(문서마다 폴더를 나눠
서로 다른 문서의 같은 파일명이 섞이지 않게 한다), 결과는 manifest.json 에 기록한다.

    python crawlling/crawl.py                       # 전체 (이미 ok 인 페이지는 건너뜀)
    python crawlling/crawl.py --categories Network,Bill
    python crawlling/crawl.py --changed             # 전부 다시 받되 본문이 바뀐 것만 저장
    python crawlling/crawl.py --force               # 전부 다시 저장
"""

import argparse
import hashlib
import os
import sys
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from crawlling.manifest import (  # noqa: E402
    STATUS_ERROR, STATUS_NO_BREADCRUMB, STATUS_OK, Entry, Manifest, content_hash, now_iso,
)
from crawlling.paths import doc_path, extract_breadcrumb, fallback_path  # noqa: E402

START_URL = "https://docs.nhncloud.com/ko/quickstarts/ko/overview/"
CONTENT_SELECTOR = "section.page__content-wrapper"
DEFAULT_SAVE_DIR = "nhn_cloud_docs"
IMAGE_TIMEOUT = 10


def build_driver() -> webdriver.Chrome:
    opts = Options()
    for flag in ("--headless=new", "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"):
        opts.add_argument(flag)
    return webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=opts)


def discover(driver) -> list[dict]:
    """GNB 를 순회해 {category, name, url} 목록을 만든다. (기존 1.menual_down.py 로직)"""
    driver.get(START_URL)
    WebDriverWait(driver, 10).until(lambda d: d.execute_script("return document.readyState") == "complete")
    WebDriverWait(driver, 20).until(lambda d: len(d.find_elements(By.CSS_SELECTOR, "li.gnb_menu")) > 0)

    count = len(driver.find_elements(By.CSS_SELECTOR, "#gnb > li.gnb_menu"))
    tasks: list[dict] = []
    seen: set[str] = set()

    for i in range(count):
        cat = driver.find_elements(By.CSS_SELECTOR, "#gnb > li.gnb_menu")[i]
        try:
            cat_link = cat.find_element(By.CSS_SELECTOR, "a.category_menu")
            category_name = cat_link.text.strip()
            category_url = cat_link.get_attribute("href")

            driver.execute_script("arguments[0].click();", cat_link)
            time.sleep(1)

            cat = driver.find_elements(By.CSS_SELECTOR, "#gnb > li.gnb_menu")[i]
            links = cat.find_elements(By.CSS_SELECTOR, "ul.lst_sub_menu a.link_txt")

            found = 0
            for link in links:
                url = link.get_attribute("href")
                name = (link.text or link.get_attribute("innerText") or link.get_attribute("textContent") or "").strip()
                if not name or not url or url.startswith("javascript") or "#" in url or url in seen:
                    continue
                seen.add(url)
                tasks.append({"category": category_name, "name": name, "url": url})
                found += 1

            if found == 0 and category_url and "javascript" not in category_url and category_url not in seen:
                seen.add(category_url)
                tasks.append({"category": category_name, "name": category_name, "url": category_url})

            print(f"[{category_name}] 링크 {found}개")
        except Exception as e:  # 카테고리 하나가 깨져도 나머지는 계속
            print(f"메뉴 탐색 오류 (카테고리 {i}): {e}")

    return tasks


def fetch_section(driver, url: str, sleep: float):
    driver.get(url)
    time.sleep(sleep)
    soup = BeautifulSoup(driver.page_source, "html.parser")
    return soup.select_one(CONTENT_SELECTOR)


def download_images(section, doc_dir: str, page_url: str, doc_name: str, refresh: bool = False) -> tuple[int, int]:
    """본문의 <img> 를 doc_dir/images/{doc_name}/ 에 받고 src 를 상대경로로 바꾼다.

    images/ 는 서비스 폴더 안 모든 문서가 공유하므로 문서마다 하위 폴더를 따로 둬,
    서로 다른 문서가 같은 파일명을 쓸 때 스크린샷이 뒤섞이는 것을 막는다.
    refresh=True 면 파일이 이미 있어도 다시 받는다(기본은 있으면 건너뜀).
    (성공, 실패) 수를 돌려준다.
    """
    img_dir = os.path.join(doc_dir, "images", doc_name)
    dir_made = False

    ok = missing = 0
    name_to_url: dict[str, str] = {}

    for img in section.find_all("img"):
        src = img.get("src")
        if not src:
            continue

        url = urljoin(page_url, src)
        name = os.path.basename(urlparse(url).path) or "image"
        # 같은 문서 안에서 다른 URL 이 같은 파일명을 쓰면 URL 해시를 접두로 붙인다.
        if name in name_to_url and name_to_url[name] != url:
            name = hashlib.sha1(url.encode("utf-8")).hexdigest()[:8] + "_" + name
        name_to_url[name] = url

        dest = os.path.join(img_dir, name)
        if refresh or not os.path.exists(dest):
            try:
                res = requests.get(url, timeout=IMAGE_TIMEOUT)
                res.raise_for_status()
                if not dir_made:
                    os.makedirs(img_dir, exist_ok=True)
                    dir_made = True
                with open(dest, "wb") as f:
                    f.write(res.content)
            except Exception as e:
                print(f"    이미지 실패: {url} ({e})")
                img["src"] = url
                img["data-missing"] = "true"
                missing += 1
                continue

        img["src"] = f"./images/{doc_name}/{name}"
        ok += 1

    return ok, missing


def save_task(task: dict, driver, manifest: Manifest, save_dir: str, args) -> str:
    """페이지 하나를 저장하고 manifest 에 기록한다. 결과 상태 문자열을 돌려준다."""
    prev = manifest.get(task["url"])

    if prev and prev.status == STATUS_OK and not (args.changed or args.force):
        return "skip"

    section = fetch_section(driver, task["url"], args.sleep)
    if section is None:
        raise RuntimeError(f"본문({CONTENT_SELECTOR}) 없음")

    raw = str(section)
    digest = content_hash(raw)
    if args.changed and prev and prev.status == STATUS_OK and prev.content_hash == digest:
        return "unchanged"

    crumbs = extract_breadcrumb(raw)
    if crumbs and len(crumbs) >= 2:
        rel = doc_path(crumbs)
        status = STATUS_OK
    else:
        rel = fallback_path(task["category"], task["name"])
        status = STATUS_NO_BREADCRUMB

    doc_dir = os.path.join(save_dir, os.path.dirname(rel))
    os.makedirs(doc_dir, exist_ok=True)

    doc_name = os.path.splitext(os.path.basename(rel))[0]
    ok, missing = download_images(section, doc_dir, task["url"], doc_name, refresh=args.changed or args.force)

    with open(os.path.join(save_dir, rel), "w", encoding="utf-8") as f:
        f.write(section.prettify())

    manifest.put(Entry(
        url=task["url"], path=rel, breadcrumb=crumbs or [], fetched_at=now_iso(),
        content_hash=digest, image_count=ok, status=status,
        error=f"missing_images={missing}" if missing else "",
    ))
    return status


def run(args) -> int:
    save_dir = args.save_dir
    os.makedirs(save_dir, exist_ok=True)
    manifest = Manifest.load(os.path.join(save_dir, "manifest.json"))

    driver = build_driver()
    counts: dict[str, int] = {}
    try:
        tasks = discover(driver)
        if args.categories:
            keep = {c.strip() for c in args.categories.split(",")}
            tasks = [t for t in tasks if t["category"] in keep]
        print(f"총 {len(tasks)}개 페이지")

        for i, task in enumerate(tasks, 1):
            label = f"[{i}/{len(tasks)}] {task['category']} > {task['name']}"
            try:
                result = save_task(task, driver, manifest, save_dir, args)
            except Exception as e:
                prev = manifest.get(task["url"])
                manifest.put(Entry(
                    url=task["url"], path=prev.path if prev else "", breadcrumb=[],
                    fetched_at=now_iso(), content_hash="", image_count=0,
                    status=STATUS_ERROR, error=str(e)[:200],
                ))
                result = STATUS_ERROR
                print(f"{label} 실패: {e}")
            else:
                print(f"{label} → {result}")
            counts[result] = counts.get(result, 0) + 1
            manifest.save()
    finally:
        driver.quit()

    print("\n=== 결과 ===")
    for k, v in sorted(counts.items()):
        print(f"  {k}: {v}")
    errors = [e for e in manifest.entries.values() if e.status == STATUS_ERROR]
    if errors:
        print(f"  실패 페이지 {len(errors)}개 (manifest.json 의 status=error 참고)")
    return 1 if errors else 0


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--save-dir", default=DEFAULT_SAVE_DIR)
    p.add_argument("--categories", default="", help="쉼표로 구분한 카테고리 이름. 비우면 전체")
    p.add_argument("--changed", action="store_true", help="전부 다시 받되 본문 해시가 바뀐 것만 저장")
    p.add_argument("--force", action="store_true", help="manifest 를 무시하고 전부 다시 저장")
    p.add_argument("--sleep", type=float, default=2.0, help="페이지 렌더링 대기 초")
    return p.parse_args(argv)


if __name__ == "__main__":
    sys.exit(run(parse_args()))
