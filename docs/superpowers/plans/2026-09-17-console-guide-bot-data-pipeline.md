# 콘솔 안내 챗봇 — 1단계: 데이터 파이프라인 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** docs.nhncloud.com 문서를 `카테고리/서비스/문서명` 구조로 유실 없이 수집하고, 섹션 단위 청크에 스크린샷·메타데이터를 붙여 pgvector에 적재한다. 기존 챗봇 UI는 새 스키마 위에서 그대로 동작한다.

**Architecture:** 크롤러는 페이지 본문의 브레드크럼 `<h2>`로 저장 경로를 정하고 이미지를 원본 파일명으로 함께 받으며 `manifest.json`에 URL·해시를 기록한다. 적재는 순수 함수 `chunker.chunk_html()`로 HTML을 섹션 청크(본문·섹션 경로·이미지 목록)로 바꾸고, 문서 단위로 커밋하며 해시가 같은 문서는 건너뛴다. 스키마는 `documents`(메타데이터 컬럼 추가)와 `questions`(2단계에서 사용)를 만든다.

**Tech Stack:** Python 3.12, BeautifulSoup4, Selenium + webdriver-manager, requests, psycopg2, pgvector(ankane/pgvector 이미지), openai SDK(NVIDIA NIM 호환), PyYAML, pytest

**Spec:** `docs/superpowers/specs/2026-09-17-console-guide-bot-design.md` — 이 계획은 스펙의 2절(구조), 3절(데이터 파이프라인), 7절(오류 처리 중 크롤러·적재 항목), 8-1절(크롤러·청킹 테스트)을 구현한다. 검색·답변·UI·운영·평가(4~6절, 8-2절)는 2단계 계획에서 다룬다.

## Global Constraints

- Python 3.12 (`%LOCALAPPDATA%\Programs\Python\Python312\python.exe`, 새 터미널에서는 `python`으로 실행됨)
- 저장 경로 규칙: `{카테고리}/{서비스}/{문서명}.html`, 서비스 없으면 `{카테고리}/_/{문서명}.html`
- 파일명 금지 문자 `\ / * ? : " < > |` 는 `_`로 치환 (기존 `clean_name` 규칙 유지)
- 이미지는 문서와 같은 폴더의 `images/`에 **원본 파일명**으로 저장
- 청크 최대 1,500자, 초과 시 문단(블록) 경계에서 분할하고 조각마다 섹션 제목 경로를 붙임
- 스크린샷 마커 형식: `[스크린샷 N: caption 앞 60자]`, N은 청크 안에서 1부터
- `doc_type`: 문서명에 `콘솔` → `console`, `API` → `api`, `개요` → `overview`, 그 외 `other`
- 임베딩 차원은 첫 호출로 자동 감지(현재 `nvidia/nemotron-3-embed-1b` = 2048)
- LLM·DB가 필요한 테스트는 `@pytest.mark.integration`으로 표시하고 기본 실행에서 제외
- 커밋 메시지 끝에 `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` 한 줄
- `.env`, `nhn_cloud_docs/`, `app/data/`, `__pycache__/`는 git에 넣지 않음
- 기존 UI(`app/ui.py`, `app/rag.py`)는 이 계획이 끝난 시점에도 `streamlit run ui.py`로 동작해야 함

---

## 파일 구조

| 파일 | 상태 | 책임 |
|---|---|---|
| `.gitignore`, `pytest.ini`, `conftest.py`, `requirements-dev.txt` | 신규 | 저장소·테스트 기반 |
| `crawlling/__init__.py` | 신규 | 패키지 표시 |
| `crawlling/paths.py` | 신규 | 브레드크럼 파싱, 저장 경로 계산, 파일명 정리 (순수 함수) |
| `crawlling/manifest.py` | 신규 | `manifest.json` 읽기/쓰기, 본문 해시 |
| `crawlling/crawl.py` | 신규 | Selenium 메뉴 탐색 + 페이지 저장 + 이미지 다운로드 + 재개/변경 감지 (기존 `1.menual_down.py`, `2.image_down.py` 대체) |
| `crawlling/requirements.txt` | 신규 | 크롤러 의존성 |
| `crawlling/tests/test_paths.py`, `test_manifest.py` | 신규 | 순수 함수 테스트 |
| `app/chunker.py` | 신규 | HTML → 섹션 청크(본문·섹션 경로·이미지) 변환 (순수 함수). 표·코드 직렬화 포함 |
| `app/db.py` | 수정 | 연결 + `init_schema()` |
| `app/ingest.py` | 재작성 | 문서 순회, 해시 비교, 청킹·임베딩·INSERT, `--rebuild` |
| `app/aliases.py` | 신규 | DB의 서비스 목록으로 `services.generated.yaml` 생성 |
| `app/rag.py` | 최소 수정 | 새 컬럼명(`source_path`)과 코사인 연산자로 두 SELECT 변경 |
| `app/requirements.txt` | 수정 | `pyyaml` 추가 |
| `app/tests/test_chunker.py`, `test_ingest_helpers.py`, `test_aliases.py`, `test_ingest_db.py` | 신규 | 청킹·헬퍼·별칭 단위 테스트, 적재 통합 테스트 |
| `docker-compose.yaml` | 수정 | `nhn_cloud_docs`를 app에 읽기 전용 마운트, `DOCS_DIR` |

기존 `crawlling/1.menual_down.py`, `2.image_down.py`는 Task 4에서 삭제한다. `app/data/`는 삭제하지 않고 `.gitignore`에만 넣는다(2단계 전체 재적재 후 정리).

---

### Task 1: git 저장소와 테스트 기반

**Files:**
- Create: `.gitignore`, `pytest.ini`, `conftest.py`, `requirements-dev.txt`, `crawlling/__init__.py`

테스트 폴더(`app/tests/`, `crawlling/tests/`)에는 `__init__.py`를 **두지 않는다**. 두면 pytest가 둘 다 `tests` 패키지로 import 하려다 충돌한다. 테스트 파일 이름은 저장소 전체에서 고유해야 한다(`test_paths`, `test_manifest`, `test_chunker`, `test_ingest_helpers`, `test_ingest_db`, `test_aliases`).

**Interfaces:**
- Produces: 저장소 루트에서 `python -m pytest` 실행 시 `app/`과 루트가 `sys.path`에 있어 `import chunker`, `from crawlling.paths import ...`가 동작한다.

- [ ] **Step 1: git 초기화와 .gitignore**

```bash
cd "C:/Users/장원준/OneDrive - 이노그리드/바탕 화면/nhn_consol_ai_agent"
git init
```

`.gitignore`:
```
.env
__pycache__/
*.pyc
.pytest_cache/
nhn_cloud_docs/
nhn_cloud_docs_*/
app/data/
*.pkl
```

- [ ] **Step 2: pytest 설정**

`pytest.ini`:
```ini
[pytest]
testpaths = app/tests crawlling/tests
markers =
    integration: 실제 DB나 LLM API가 필요한 테스트
addopts = -m "not integration"
```

`conftest.py` (저장소 루트):
```python
import pathlib
import sys

ROOT = pathlib.Path(__file__).parent
# app/ 안의 모듈(chunker, db, ingest …)은 패키지가 아니라 최상위 모듈로 import 한다.
for p in (str(ROOT), str(ROOT / "app")):
    if p not in sys.path:
        sys.path.insert(0, p)
```

`requirements-dev.txt`:
```
pytest
```

빈 파일 생성: `crawlling/__init__.py` (그리고 빈 폴더 `crawlling/tests/`, `app/tests/`)

- [ ] **Step 3: 의존성 설치와 빈 테스트 실행**

Run:
```bash
python -m pip install -r requirements-dev.txt
python -m pytest
```
Expected: `no tests ran` (오류 없음)

- [ ] **Step 4: 기존 코드를 기준 커밋으로**

```bash
git add -A
git commit -m "chore: 기존 RAG 챗봇 코드를 기준 커밋으로 등록하고 pytest 기반 추가

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: 브레드크럼 → 저장 경로 (`crawlling/paths.py`)

**Files:**
- Create: `crawlling/paths.py`
- Test: `crawlling/tests/test_paths.py`

**Interfaces:**
- Produces:
  - `clean_name(text: str) -> str` — 앞뒤 공백 제거, 금지 문자를 `_`로
  - `parse_breadcrumb(text: str) -> list[str]` — `>`로 나누고 빈 조각 제거
  - `doc_path(parts: list[str]) -> str` — `"Compute/Virtual Desktop/콘솔 사용 가이드.html"`. 2단이면 서비스 `_`, 4단 이상이면 가운데를 `" - "`로 이어 서비스로. 1단 이하면 `ValueError`
  - `extract_breadcrumb(html: str) -> list[str] | None` — 첫 `<h2>` 텍스트에 `>`가 있으면 파싱, 아니면 `None`
  - `fallback_path(category: str, menu_name: str) -> str` — `"{category}/_/{menu_name}.html"`

- [ ] **Step 1: 실패하는 테스트 작성**

`crawlling/tests/test_paths.py`:
```python
import pytest

from crawlling.paths import (
    clean_name,
    doc_path,
    extract_breadcrumb,
    fallback_path,
    parse_breadcrumb,
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
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest crawlling/tests/test_paths.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'crawlling.paths'`

- [ ] **Step 3: 구현**

`crawlling/paths.py`:
```python
"""브레드크럼에서 저장 경로를 만든다.

docs.nhncloud.com 페이지 본문의 첫 <h2>는 "Compute > Virtual Desktop > 콘솔 사용 가이드"
형태의 브레드크럼이다. 메뉴 링크 이름만으로 파일명을 정하면 같은 카테고리의 여러
서비스가 서로 덮어쓰므로, 이 브레드크럼을 경로의 원천으로 쓴다.
"""

import re

from bs4 import BeautifulSoup

BREADCRUMB_SEP = ">"
NO_SERVICE = "_"
_FORBIDDEN = re.compile(r'[\\/*?:"<>|]')


def clean_name(text: str) -> str:
    """폴더·파일명으로 쓸 수 없는 문자를 _ 로 바꾼다."""
    return _FORBIDDEN.sub("_", text.strip())


def parse_breadcrumb(text: str) -> list[str]:
    parts = [p.strip() for p in text.split(BREADCRUMB_SEP)]
    return [p for p in parts if p]


def doc_path(parts: list[str]) -> str:
    """브레드크럼 조각 -> '카테고리/서비스/문서명.html'.

    2단이면 서비스 자리에 NO_SERVICE, 4단 이상이면 가운데를 ' - ' 로 이어 서비스로 본다.
    """
    if len(parts) < 2:
        raise ValueError(f"브레드크럼이 2단 미만입니다: {parts}")

    category = clean_name(parts[0])
    doc = clean_name(parts[-1])
    service = " - ".join(clean_name(p) for p in parts[1:-1]) or NO_SERVICE
    return f"{category}/{service}/{doc}.html"


def extract_breadcrumb(html: str) -> list[str] | None:
    soup = BeautifulSoup(html, "html.parser")
    h2 = soup.find("h2")
    if h2 is None:
        return None

    text = h2.get_text(" ", strip=True)
    if BREADCRUMB_SEP not in text:
        return None

    return parse_breadcrumb(text)


def fallback_path(category: str, menu_name: str) -> str:
    """브레드크럼이 없는 페이지는 메뉴 이름으로 저장한다."""
    return f"{clean_name(category)}/{NO_SERVICE}/{clean_name(menu_name)}.html"
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest crawlling/tests/test_paths.py -v`
Expected: 11 passed

- [ ] **Step 5: 커밋**

```bash
git add crawlling/paths.py crawlling/tests/test_paths.py
git commit -m "feat(crawler): 브레드크럼으로 카테고리/서비스/문서 저장 경로 계산

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: manifest (`crawlling/manifest.py`)

**Files:**
- Create: `crawlling/manifest.py`
- Test: `crawlling/tests/test_manifest.py`

**Interfaces:**
- Produces:
  - `@dataclass Entry(url, path, breadcrumb: list[str], fetched_at, content_hash, image_count, status, error="")` — `status`는 `"ok" | "error" | "no_breadcrumb"`
  - `content_hash(text: str) -> str` — sha256 hex
  - `now_iso() -> str` — UTC ISO 8601 초 단위
  - `class Manifest` — `Manifest.load(path)`, `.save()`, `.get(url) -> Entry | None`, `.put(entry)`, `.by_path() -> dict[path, Entry]`, `.entries: dict[url, Entry]`
- 파일 형식: `{url: Entry 필드 dict}` JSON, UTF-8, 임시 파일에 쓴 뒤 `os.replace`로 교체(중단 시 손상 방지)

- [ ] **Step 1: 실패하는 테스트 작성**

`crawlling/tests/test_manifest.py`:
```python
from crawlling.manifest import Entry, Manifest, content_hash, now_iso


def make_entry(**over):
    base = dict(
        url="https://docs.nhncloud.com/ko/a/",
        path="A/_/b.html",
        breadcrumb=["A", "b"],
        fetched_at="2026-09-17T00:00:00+00:00",
        content_hash="abc",
        image_count=2,
        status="ok",
    )
    base.update(over)
    return Entry(**base)


def test_load_missing_file_gives_empty_manifest(tmp_path):
    m = Manifest.load(str(tmp_path / "manifest.json"))
    assert m.entries == {}


def test_roundtrip_preserves_entries(tmp_path):
    path = str(tmp_path / "manifest.json")
    m = Manifest.load(path)
    m.put(make_entry())
    m.put(make_entry(url="https://docs.nhncloud.com/ko/c/", path="C/D/e.html", status="error", error="timeout"))
    m.save()

    m2 = Manifest.load(path)
    assert m2.get("https://docs.nhncloud.com/ko/a/") == make_entry()
    assert m2.get("https://docs.nhncloud.com/ko/c/").error == "timeout"
    assert m2.get("https://docs.nhncloud.com/ko/zzz/") is None


def test_by_path_indexes_entries(tmp_path):
    m = Manifest.load(str(tmp_path / "m.json"))
    m.put(make_entry())
    assert m.by_path()["A/_/b.html"].content_hash == "abc"


def test_save_leaves_no_temp_file(tmp_path):
    path = tmp_path / "manifest.json"
    m = Manifest.load(str(path))
    m.put(make_entry())
    m.save()
    assert path.exists()
    assert not (tmp_path / "manifest.json.tmp").exists()


def test_content_hash_is_deterministic_and_distinct():
    assert content_hash("가") == content_hash("가")
    assert content_hash("가") != content_hash("나")
    assert len(content_hash("x")) == 64


def test_now_iso_has_timezone():
    assert now_iso().endswith("+00:00")
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest crawlling/tests/test_manifest.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'crawlling.manifest'`

- [ ] **Step 3: 구현**

`crawlling/manifest.py`:
```python
"""수집 결과 목록(manifest.json).

문서마다 원본 URL, 저장 경로, 브레드크럼, 본문 해시를 기록한다.
재개(이미 받은 페이지 건너뛰기), 변경 감지(--changed), 적재 시 원본 URL 조회에 쓴다.
"""

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

STATUS_OK = "ok"
STATUS_ERROR = "error"
STATUS_NO_BREADCRUMB = "no_breadcrumb"


@dataclass
class Entry:
    url: str
    path: str
    breadcrumb: list[str]
    fetched_at: str
    content_hash: str
    image_count: int
    status: str
    error: str = ""


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Manifest:
    def __init__(self, path: str):
        self.path = path
        self.entries: dict[str, Entry] = {}

    @classmethod
    def load(cls, path: str) -> "Manifest":
        m = cls(path)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                for url, fields in json.load(f).items():
                    m.entries[url] = Entry(**fields)
        return m

    def save(self) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(
                {url: asdict(e) for url, e in self.entries.items()},
                f, ensure_ascii=False, indent=1,
            )
        os.replace(tmp, self.path)

    def get(self, url: str) -> Entry | None:
        return self.entries.get(url)

    def put(self, entry: Entry) -> None:
        self.entries[entry.url] = entry

    def by_path(self) -> dict[str, Entry]:
        return {e.path: e for e in self.entries.values()}
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest crawlling/tests/test_manifest.py -v`
Expected: 6 passed

- [ ] **Step 5: 커밋**

```bash
git add crawlling/manifest.py crawlling/tests/test_manifest.py
git commit -m "feat(crawler): manifest.json 읽기/쓰기와 본문 해시

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: 크롤러 통합 (`crawlling/crawl.py`) + 시범 수집

**Files:**
- Create: `crawlling/crawl.py`, `crawlling/requirements.txt`
- Delete: `crawlling/1.menual_down.py`, `crawlling/2.image_down.py`

**Interfaces:**
- Consumes: Task 2의 `extract_breadcrumb`, `doc_path`, `fallback_path`; Task 3의 `Manifest`, `Entry`, `content_hash`, `now_iso`
- Produces:
  - CLI: `python crawlling/crawl.py [--save-dir DIR] [--categories "A,B"] [--changed] [--force] [--sleep 초]`
  - 저장 결과: `DIR/{카테고리}/{서비스}/{문서명}.html`, `DIR/.../images/{원본파일명}`, `DIR/manifest.json`
  - 저장된 HTML은 `section.page__content-wrapper` 내부만이며 `<img src>`는 `./images/{파일명}` (다운로드 실패 시 원본 절대 URL + `data-missing="true"`)
  - `download_images(section, doc_dir, page_url) -> tuple[int, int]` — (성공, 실패) 수. 다른 URL이 같은 파일명이면 URL sha1 앞 8자를 접두로 붙인다

Selenium은 단위 테스트하지 않는다. 이 태스크의 검증은 실제 사이트에 대한 시범 수집이다.

**전제:** 이 PC에 Chrome이 설치돼 있어야 한다. `webdriver-manager`가 맞는 chromedriver를 받는다.

- [ ] **Step 1: 의존성**

`crawlling/requirements.txt`:
```
selenium
webdriver-manager
beautifulsoup4
requests
```

Run: `python -m pip install -r crawlling/requirements.txt`

- [ ] **Step 2: 구현**

`crawlling/crawl.py`:
```python
"""docs.nhncloud.com 문서 수집기.

메뉴(GNB)에서 모든 문서 링크를 모은 뒤, 페이지 본문(section.page__content-wrapper)만
'카테고리/서비스/문서명.html' 로 저장한다. 경로는 본문 첫 <h2>의 브레드크럼으로 정한다.
이미지는 같은 폴더의 images/ 에 원본 파일명으로 받고, 결과는 manifest.json 에 기록한다.

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


def download_images(section, doc_dir: str, page_url: str) -> tuple[int, int]:
    """본문의 <img> 를 doc_dir/images/ 에 받고 src 를 상대경로로 바꾼다. (성공, 실패) 수를 돌려준다."""
    img_dir = os.path.join(doc_dir, "images")
    os.makedirs(img_dir, exist_ok=True)

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
        if not os.path.exists(dest):
            try:
                res = requests.get(url, timeout=IMAGE_TIMEOUT)
                res.raise_for_status()
                with open(dest, "wb") as f:
                    f.write(res.content)
            except Exception as e:
                print(f"    이미지 실패: {url} ({e})")
                img["src"] = url
                img["data-missing"] = "true"
                missing += 1
                continue

        img["src"] = f"./images/{name}"
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

    ok, missing = download_images(section, doc_dir, task["url"])

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
```

- [ ] **Step 3: 기존 스크립트 삭제**

```bash
git rm crawlling/1.menual_down.py crawlling/2.image_down.py
```

- [ ] **Step 4: 시범 수집 (카테고리 2개, 별도 폴더)**

Run:
```bash
python crawlling/crawl.py --save-dir nhn_cloud_docs_pilot --categories "Network,Bill"
```
Expected: 오류 없이 종료. `=== 결과 ===`에 `ok` 수십 건, `error` 0 (있으면 `manifest.json`의 `error` 필드로 원인 확인. 일시적 로딩 실패면 같은 명령을 다시 실행 — `ok`인 페이지는 건너뛰고 실패분만 재시도된다).

- [ ] **Step 5: 저장 구조 확인**

Run (Git Bash):
```bash
find nhn_cloud_docs_pilot -name "*.html" | head -20
find nhn_cloud_docs_pilot -name "*.html" | wc -l
find nhn_cloud_docs_pilot -path "*/images/*" -type f | wc -l
python -c "import json; m=json.load(open('nhn_cloud_docs_pilot/manifest.json',encoding='utf-8')); import collections; print(collections.Counter(e['status'] for e in m.values()))"
```
Expected:
- 경로가 `nhn_cloud_docs_pilot/Network/VPC/콘솔 사용 가이드.html`처럼 **3단**이고, Network 아래에 서비스 폴더가 여러 개(VPC, Load Balancer 등)
- 이미지 파일명이 `img_0.png`가 아니라 원본 이름
- status가 대부분 `ok`. `no_breadcrumb`가 있으면 그 파일을 열어 첫 h2를 확인하고 여기에 기록해 둔다(2단계에서 참고)

- [ ] **Step 6: 재개 동작 확인**

Run: `python crawlling/crawl.py --save-dir nhn_cloud_docs_pilot --categories "Network,Bill"`
Expected: 모든 페이지가 `skip`, 수 초 내 종료 (Selenium 메뉴 탐색 시간 제외)

- [ ] **Step 7: 커밋**

```bash
git add crawlling/crawl.py crawlling/requirements.txt
git commit -m "feat(crawler): 브레드크럼 경로·원본 파일명 이미지·manifest 기반 수집기로 교체

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: 섹션 청커 (`app/chunker.py`)

**Files:**
- Create: `app/chunker.py`
- Test: `app/tests/test_chunker.py`

**Interfaces:**
- Produces:
  - `@dataclass Image(path: str, caption: str, alt: str = "")` — `path`는 문서 루트 기준 상대 경로(`"Network/VPC/images/subnet_01.png"`), 원본 URL이면 그대로
  - `@dataclass Chunk(content: str, section_path: str, images: list[Image])`
  - `chunk_html(html: str, doc_title: str, doc_rel_dir: str, max_chars: int = 1500) -> list[Chunk]`
    - 첫 `<h2>`가 브레드크럼(`>` 포함)이면 섹션으로 만들지 않는다
    - 섹션 = h2/h3/h4 제목부터 다음 같은 급 이상 제목 전까지. `section_path`는 `"h2제목 > h3제목 > h4제목"` 중 있는 것만
    - `content` 첫 줄은 `"{doc_title} > {section_path}"` (section_path 없으면 doc_title만), 이어서 블록 텍스트, 이미지 마커 `[스크린샷 N: caption 앞 60자]`
    - 이미지는 자신이 속한 블록(p/li/td/blockquote)에, 블록 밖 단독 이미지는 직전 블록 텍스트를 caption으로
    - 블록 누적 길이가 `max_chars`를 넘으면 블록 경계에서 새 청크. 각 조각은 같은 첫 줄을 갖고 이미지 번호는 조각 안에서 1부터
  - `table_to_text(table) -> str` — 기존 `ingest.py`의 구현을 옮김 (헤더: 값 쌍)

- [ ] **Step 1: 실패하는 테스트 작성**

`app/tests/test_chunker.py`:
```python
from chunker import Chunk, Image, chunk_html

DOC_TITLE = "콘솔 사용 가이드"
DOC_DIR = "Network/VPC"

HTML = """
<section>
<h2 id="crumb">Network &gt; VPC &gt; 콘솔 사용 가이드</h2>
<h2>서브넷</h2>
<h3>서브넷 생성</h3>
<p>왼쪽 메뉴에서 Network &gt; Subnet을 클릭합니다.</p>
<p>서브넷 생성 버튼을 클릭합니다. <img src="./images/subnet_01.png" alt="subnet_01.png"></p>
<ul><li>이름을 입력합니다.</li><li>CIDR을 입력합니다.</li></ul>
<img src="./images/subnet_02.png" alt="">
<h3>서브넷 삭제</h3>
<p>삭제할 서브넷을 선택하고 삭제를 클릭합니다.</p>
<table><tr><th>이름</th><th>설명</th></tr><tr><td>CIDR</td><td>대역</td></tr></table>
<pre>curl -X DELETE /subnets</pre>
</section>
"""


def chunks():
    return chunk_html(HTML, DOC_TITLE, DOC_DIR)


def test_breadcrumb_h2_is_metadata_not_a_section():
    assert all("Network > VPC" not in c.section_path for c in chunks())


def test_sections_follow_heading_hierarchy():
    assert [c.section_path for c in chunks()] == ["서브넷 > 서브넷 생성", "서브넷 > 서브넷 삭제"]


def test_content_starts_with_title_and_section_path():
    first = chunks()[0]
    assert first.content.startswith("콘솔 사용 가이드 > 서브넷 > 서브넷 생성\n")
    assert "왼쪽 메뉴에서 Network > Subnet을 클릭합니다." in first.content


def test_image_inside_block_uses_block_text_as_caption():
    img = chunks()[0].images[0]
    assert img == Image(path="Network/VPC/images/subnet_01.png",
                        caption="서브넷 생성 버튼을 클릭합니다.", alt="subnet_01.png")
    assert "[스크린샷 1: 서브넷 생성 버튼을 클릭합니다.]" in chunks()[0].content


def test_standalone_image_uses_previous_block_as_caption():
    img = chunks()[0].images[1]
    assert img.path == "Network/VPC/images/subnet_02.png"
    assert img.caption == "CIDR을 입력합니다."
    assert "[스크린샷 2: CIDR을 입력합니다.]" in chunks()[0].content


def test_marker_follows_its_block():
    content = chunks()[0].content
    assert content.index("서브넷 생성 버튼을 클릭합니다.") < content.index("[스크린샷 1:")
    assert content.index("[스크린샷 1:") < content.index("이름을 입력합니다.")


def test_table_and_code_are_preserved():
    second = chunks()[1]
    assert "이름 | 설명" in second.content
    assert "이름: CIDR | 설명: 대역" in second.content
    assert "[코드]\ncurl -X DELETE /subnets" in second.content
    assert second.images == []


def test_absolute_image_url_is_kept_as_is():
    html = '<section><h3>A</h3><p>본문 <img src="https://x/y.png" alt="y"></p></section>'
    assert chunk_html(html, "t", "C/S")[0].images[0].path == "https://x/y.png"


def test_long_section_splits_at_block_boundary_with_header_on_each_piece():
    paragraphs = "".join(f"<p>{'가' * 400} {i}</p>" for i in range(5))
    paragraphs += '<p>마지막 문단 <img src="./images/last.png" alt=""></p>'
    html = f"<section><h3>긴 절</h3>{paragraphs}</section>"

    result = chunk_html(html, "문서", "C/S", max_chars=1000)

    assert len(result) == 3                      # 400자 문단 2개씩 + 마지막 조각
    assert all(c.content.startswith("문서 > 긴 절\n") for c in result)
    assert all(c.section_path == "긴 절" for c in result)
    assert result[-1].images == [Image(path="C/S/images/last.png", caption="마지막 문단", alt="")]
    assert "[스크린샷 1: 마지막 문단]" in result[-1].content
    assert result[0].images == []


def test_caption_marker_is_cut_at_60_chars():
    long_text = "가" * 100
    html = f'<section><h3>A</h3><p>{long_text} <img src="./images/a.png"></p></section>'
    c = chunk_html(html, "t", "C/S")[0]
    assert f"[스크린샷 1: {'가' * 60}]" in c.content
    assert c.images[0].caption == long_text


def test_content_before_any_heading_goes_to_title_only_section():
    html = "<section><p>개요 문단</p><h3>A</h3><p>본문</p></section>"
    result = chunk_html(html, "문서", "C/S")
    assert result[0].section_path == ""
    assert result[0].content == "문서\n개요 문단"
    assert result[1].section_path == "A"


def test_empty_html_gives_no_chunks():
    assert chunk_html("<section></section>", "t", "C/S") == []
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest app/tests/test_chunker.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'chunker'`

- [ ] **Step 3: 구현**

`app/chunker.py`:
```python
"""HTML 문서를 섹션 단위 청크로 바꾼다.

NHN Cloud 콘솔 가이드는 h3/h4 하나가 작업 단계 묶음이고, 스크린샷은 대부분(92%)
설명 문단 바로 뒤에 온다. 그래서 섹션을 청크 단위로 삼고, 이미지는 자기가 속한
블록(문단·목록 항목·표 칸)에 묶어 캡션을 그 블록 텍스트로 잡는다.
"""

from dataclasses import dataclass, field

from bs4 import BeautifulSoup

MAX_CHARS = 1500
CAPTION_CHARS = 60

HEADING_LEVELS = {"h2": 2, "h3": 3, "h4": 4}
BLOCK_TAGS = ["h2", "h3", "h4", "h5", "h6", "p", "li", "pre", "table", "blockquote", "img"]


@dataclass
class Image:
    path: str
    caption: str
    alt: str = ""


@dataclass
class Chunk:
    content: str
    section_path: str
    images: list[Image] = field(default_factory=list)


def table_to_text(table) -> str:
    """표를 행 단위로 편다. 헤더가 있으면 '헤더: 값' 쌍으로 만들어 행이 스스로를 설명하게 한다."""
    lines = []

    caption = table.find("caption")
    if caption:
        lines.append(f"[표] {caption.get_text(' ', strip=True)}")

    headers: list[str] = []
    for tr in table.find_all("tr"):
        cells = tr.find_all(["th", "td"])
        if not cells:
            continue

        values = [c.get_text(" ", strip=True) for c in cells]
        if not any(values):
            continue

        if not headers and all(c.name == "th" for c in cells):
            headers = values
            lines.append(" | ".join(values))
            continue

        if headers and len(headers) == len(values):
            lines.append(" | ".join(f"{h}: {v}" for h, v in zip(headers, values) if v))
        else:
            lines.append(" | ".join(values))

    return "\n".join(lines)


def _block_text(el) -> str:
    if el.name == "table":
        return table_to_text(el)
    if el.name == "pre":
        return "[코드]\n" + el.get_text().strip()
    return el.get_text(" ", strip=True)


def _image(img, caption: str, doc_rel_dir: str) -> Image:
    src = (img.get("src") or "").strip()
    if src.startswith("./"):
        path = f"{doc_rel_dir}/{src[2:]}"
    elif src.startswith(("http://", "https://")):
        path = src
    else:
        path = f"{doc_rel_dir}/{src}"
    return Image(path=path, caption=caption, alt=img.get("alt") or "")


def _section_path(stack: dict[int, str]) -> str:
    return " > ".join(stack[level] for level in (2, 3, 4) if stack[level])


def _build_chunks(doc_title: str, section_path: str, blocks: list[tuple[str, list[Image]]], max_chars: int) -> list[Chunk]:
    header = f"{doc_title} > {section_path}" if section_path else doc_title

    pieces: list[list[tuple[str, list[Image]]]] = []
    current: list[tuple[str, list[Image]]] = []
    length = 0
    for text, images in blocks:
        if current and length + len(text) + 1 > max_chars:
            pieces.append(current)
            current, length = [], 0
        current.append((text, images))
        length += len(text) + 1
    if current:
        pieces.append(current)

    chunks = []
    for piece in pieces:
        lines = [header]
        images: list[Image] = []
        for text, block_images in piece:
            if text:
                lines.append(text)
            for image in block_images:
                images.append(image)
                lines.append(f"[스크린샷 {len(images)}: {image.caption[:CAPTION_CHARS]}]")
        chunks.append(Chunk(content="\n".join(lines), section_path=section_path, images=images))
    return chunks


def chunk_html(html: str, doc_title: str, doc_rel_dir: str, max_chars: int = MAX_CHARS) -> list[Chunk]:
    soup = BeautifulSoup(html, "html.parser")

    # 첫 h2 가 브레드크럼이면 메타데이터일 뿐이므로 본문에서 뺀다.
    first_h2 = soup.find("h2")
    if first_h2 is not None and ">" in first_h2.get_text(" ", strip=True):
        first_h2.decompose()

    stack = {2: "", 3: "", 4: ""}
    sections: list[tuple[str, list[tuple[str, list[Image]]]]] = []
    blocks: list[tuple[str, list[Image]]] = []
    consumed: set[int] = set()
    last_text = ""

    def flush():
        nonlocal blocks
        if blocks:
            sections.append((_section_path(stack), blocks))
        blocks = []

    # find_all 은 문서 순서라 상위 블록이 먼저 온다. 상위가 처리한 요소의 하위는 건너뛴다.
    for el in soup.find_all(BLOCK_TAGS):
        if any(id(p) in consumed for p in el.parents):
            continue
        consumed.add(id(el))

        level = HEADING_LEVELS.get(el.name)
        if level:
            flush()
            stack[level] = el.get_text(" ", strip=True)
            for deeper in range(level + 1, 5):
                stack[deeper] = ""
            continue

        if el.name == "img":
            text, images = "", [_image(el, last_text, doc_rel_dir)]
        else:
            text = _block_text(el)
            images = [_image(img, text, doc_rel_dir) for img in el.find_all("img")]

        if not text and not images:
            continue
        if text:
            last_text = text
        blocks.append((text, images))

    flush()

    return [
        chunk
        for section_path, section_blocks in sections
        for chunk in _build_chunks(doc_title, section_path, section_blocks, max_chars)
    ]
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest app/tests/test_chunker.py -v`
Expected: 12 passed

- [ ] **Step 5: 실제 문서로 눈 확인**

Run:
```bash
python -c "
import io, chunker, sys; sys.path.insert(0,'app')
html = io.open('nhn_cloud_docs_pilot/Network/VPC/콘솔 사용 가이드.html', encoding='utf-8').read()
cs = chunker.chunk_html(html, '콘솔 사용 가이드', 'Network/VPC')
print(len(cs), '청크'); [print('-', c.section_path, '/', len(c.content), '자 /', len(c.images), '장') for c in cs[:15]]
print(); print(cs[1].content[:600])
"
```
(경로는 시범 수집 결과에 있는 콘솔 가이드 하나로 바꿔도 된다.)
Expected: 섹션 경로가 문서 제목 구조와 맞고, 이미지가 있는 섹션에 `[스크린샷 N: …]` 마커가 해당 문단 뒤에 있다.

- [ ] **Step 6: 커밋**

```bash
git add app/chunker.py app/tests/test_chunker.py
git commit -m "feat(ingest): 섹션 단위 청커 — 제목 계층, 스크린샷 소속, 길이 분할

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: 스키마와 적재 헬퍼 (`app/db.py`, `app/ingest.py` 순수 함수)

**Files:**
- Modify: `app/db.py`
- Create: `app/ingest.py` (재작성 — 이 태스크에서는 순수 함수만, 실행 흐름은 Task 7)
- Test: `app/tests/test_ingest_helpers.py`

**Interfaces:**
- Produces (`db.py`):
  - `init_schema(conn, dim: int, rebuild: bool = False) -> None` — `vector` 확장, `documents`(스펙 3-3 컬럼), `questions`, 인덱스 생성. `rebuild=True`면 `documents`를 지우고 새로 만든다. 기존 `documents`에 `content_hash` 컬럼이 없으면(구 스키마) `RuntimeError("구 스키마입니다. --rebuild 로 실행하세요")`. HNSW 인덱스 생성이 실패하면(pgvector 구버전) 경고만 출력하고 계속한다
- Produces (`ingest.py`):
  - `doc_type_of(doc_title: str) -> str` — `console | api | overview | other`
  - `split_source_path(rel_path: str) -> tuple[str, str, str]` — `(category, service, doc_title)`. 역슬래시 허용. 2단 경로(`Bill/x.html`)는 service `_`
  - `DOCS_DIR` — 환경변수 `DOCS_DIR`, 기본값은 `app/../nhn_cloud_docs`

- [ ] **Step 1: 실패하는 테스트 작성**

`app/tests/test_ingest_helpers.py`:
```python
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
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest app/tests/test_ingest_helpers.py -v`
Expected: FAIL — 아직 구 `ingest.py`라서 import 시 `RuntimeError: NVIDIA_API_KEY 가 설정되지 않았습니다`(llm 모듈이 최상위에서 import됨) 또는 `ImportError: cannot import name 'doc_type_of'`. 어느 쪽이든 실패면 된다. 새 `ingest.py`는 `llm`을 함수 안에서 import 해 키 없이도 import 되게 만든다(Task 7).

- [ ] **Step 3: `db.py`에 `init_schema` 추가**

`app/db.py` 전체:
```python
import os

import psycopg2

# 컨테이너 안에서는 서비스명 "db", 호스트(윈도우)에서 직접 돌릴 때는
# DB_HOST=localhost 로 덮어쓴다. 5432 는 compose 에서 이미 공개돼 있다.
DB_HOST = os.getenv("DB_HOST", "db")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "ragdb")
DB_USER = os.getenv("DB_USER", "devops")
DB_PASSWORD = os.getenv("DB_PASSWORD", "devops")


def get_conn():
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
    )


def _has_column(cur, table: str, column: str) -> bool:
    cur.execute(
        "SELECT 1 FROM information_schema.columns WHERE table_name = %s AND column_name = %s",
        (table, column),
    )
    return cur.fetchone() is not None


def _table_exists(cur, table: str) -> bool:
    cur.execute("SELECT 1 FROM information_schema.tables WHERE table_name = %s", (table,))
    return cur.fetchone() is not None


def init_schema(conn, dim: int, rebuild: bool = False) -> None:
    """documents / questions 테이블과 인덱스를 만든다.

    rebuild=False 인데 구 스키마(content_hash 없음)가 남아 있으면 멈춘다 —
    그 위에 새 형식으로 INSERT 하면 실패하므로 명시적으로 --rebuild 를 요구한다.
    """
    cur = conn.cursor()
    cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    if rebuild:
        cur.execute("DROP TABLE IF EXISTS documents;")
    elif _table_exists(cur, "documents") and not _has_column(cur, "documents", "content_hash"):
        raise RuntimeError("documents 테이블이 구 스키마입니다. python ingest.py --rebuild 로 실행하세요.")

    cur.execute(f"""
    CREATE TABLE IF NOT EXISTS documents (
        id           SERIAL PRIMARY KEY,
        content      TEXT NOT NULL,
        embedding    VECTOR({dim}),
        category     TEXT NOT NULL,
        service      TEXT NOT NULL,
        doc_type     TEXT NOT NULL,
        doc_title    TEXT NOT NULL,
        section_path TEXT NOT NULL,
        source_path  TEXT NOT NULL,
        source_url   TEXT,
        content_hash TEXT NOT NULL,
        images       JSONB NOT NULL DEFAULT '[]'
    );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS documents_service_doc_type ON documents (service, doc_type);")
    cur.execute("CREATE INDEX IF NOT EXISTS documents_source_path ON documents (source_path);")

    # HNSW 는 pgvector 0.5 이상. 구버전이면 인덱스 없이 순차 스캔으로 동작한다.
    cur.execute("SAVEPOINT hnsw;")
    try:
        cur.execute(
            "CREATE INDEX IF NOT EXISTS documents_embedding_hnsw "
            "ON documents USING hnsw (embedding vector_cosine_ops);"
        )
    except psycopg2.Error as e:
        cur.execute("ROLLBACK TO SAVEPOINT hnsw;")
        print(f"  [경고] HNSW 인덱스를 만들지 못했습니다 (pgvector 버전 확인): {str(e).strip()}")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS questions (
        id          SERIAL PRIMARY KEY,
        asked_at    TIMESTAMPTZ DEFAULT now(),
        question    TEXT NOT NULL,
        service     TEXT,
        intent      TEXT,
        grounded    BOOLEAN,
        elapsed_ms  INTEGER,
        sources     JSONB,
        error       TEXT,
        feedback    SMALLINT
    );
    """)

    conn.commit()
    cur.close()
```

- [ ] **Step 4: `ingest.py`를 헬퍼부터 새로 작성**

`app/ingest.py` (이 단계에서는 헬퍼와 상수만. 실행 흐름은 Task 7에서 이어 붙인다):
```python
"""nhn_cloud_docs/ 의 HTML 을 섹션 청크로 나눠 pgvector 에 적재한다.

    python ingest.py                 # 바뀐 문서만 (source_path + content_hash 비교)
    python ingest.py --rebuild       # 테이블을 지우고 전부 다시
    python ingest.py --limit 20      # 앞 20개 문서만 (시범)

문서 경로 규칙 '카테고리/서비스/문서명.html' 에서 category/service/doc_title 을,
문서명에서 doc_type 을 정한다. 이미지는 DB 에 넣지 않고 경로만 청크 메타에 둔다.
"""

import os

DOCS_DIR = os.getenv(
    "DOCS_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "nhn_cloud_docs"),
)
NO_SERVICE = "_"
BATCH_SIZE = 32


def doc_type_of(doc_title: str) -> str:
    upper = doc_title.upper()
    if "콘솔" in doc_title:
        return "console"
    if "API" in upper:
        return "api"
    if "개요" in doc_title:
        return "overview"
    return "other"


def split_source_path(rel_path: str) -> tuple[str, str, str]:
    """'카테고리/서비스/문서명.html' -> (category, service, doc_title)."""
    parts = rel_path.replace("\\", "/").strip("/").split("/")
    doc_title = os.path.splitext(parts[-1])[0]
    category = parts[0]
    service = parts[1] if len(parts) >= 3 else NO_SERVICE
    return category, service, doc_title
```

- [ ] **Step 5: 통과 확인**

Run: `python -m pytest app/tests/test_ingest_helpers.py -v`
Expected: 8 passed

- [ ] **Step 6: 커밋**

```bash
git add app/db.py app/ingest.py app/tests/test_ingest_helpers.py
git commit -m "feat(ingest): 새 documents/questions 스키마와 경로·문서종류 헬퍼

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: 적재 실행 흐름 + 기존 UI 호환 + compose 마운트

**Files:**
- Modify: `app/ingest.py` (Task 6의 헬퍼 아래에 실행 흐름 추가)
- Modify: `app/rag.py` — `build_bm25()`의 SELECT(현재 24행 부근)와 `hybrid_search()`의 벡터 SELECT(67~72행 부근)
- Modify: `docker-compose.yaml`
- Test: `app/tests/test_ingest_db.py` (integration)

**Interfaces:**
- Consumes: Task 5 `chunk_html`, Task 6 `init_schema`·`doc_type_of`·`split_source_path`, 기존 `llm.embed(texts, input_type)`·`llm.embed_one`, Task 3 manifest 파일 형식
- Produces:
  - `iter_documents(docs_dir) -> Iterator[str]` — `manifest.json`을 제외한 `.html`의 문서 루트 기준 상대 경로(`/` 구분), 정렬
  - `load_manifest_urls(docs_dir) -> dict[str, str]` — `{상대 경로: 원본 URL}`, manifest 없으면 `{}`
  - `existing_hash(cur, source_path) -> str | None`
  - `ingest_document(conn, docs_dir, rel_path, url) -> int` — 청크 수. 기존 행 삭제 후 삽입, 문서 단위 커밋
  - `run(argv) -> int` — CLI 진입점. 끝에 `완료: 문서 N개 적재, M개 건너뜀, K개 실패 (청크 C개)` 출력, 실패 문서 목록 출력, 실패가 있으면 종료 코드 1
  - `documents` 행은 스펙 3-3 스키마. `images`는 `[{"path","caption","alt"}]` JSON

- [ ] **Step 1: 실패하는 통합 테스트 작성**

`app/tests/test_ingest_db.py`:
```python
"""실제 pgvector + 임베딩 API 가 필요하다.  python -m pytest -m integration app/tests/test_ingest_db.py"""
import json
import os

import pytest

pytestmark = pytest.mark.integration

HTML = """<section>
<h2>Network &gt; VPC &gt; 콘솔 사용 가이드</h2>
<h3>서브넷 생성</h3>
<p>서브넷 생성 버튼을 클릭합니다. <img src="./images/s1.png" alt=""></p>
<h3>서브넷 삭제</h3>
<p>삭제를 클릭합니다.</p>
</section>"""


@pytest.fixture
def docs_dir(tmp_path):
    doc = tmp_path / "Network" / "VPC"
    doc.mkdir(parents=True)
    (doc / "콘솔 사용 가이드.html").write_text(HTML, encoding="utf-8")
    (tmp_path / "manifest.json").write_text(json.dumps({
        "https://docs.nhncloud.com/ko/x/": {
            "url": "https://docs.nhncloud.com/ko/x/", "path": "Network/VPC/콘솔 사용 가이드.html",
            "breadcrumb": ["Network", "VPC", "콘솔 사용 가이드"], "fetched_at": "2026-09-17T00:00:00+00:00",
            "content_hash": "x", "image_count": 1, "status": "ok", "error": "",
        }
    }), encoding="utf-8")
    return str(tmp_path)


@pytest.fixture
def conn():
    from db import get_conn
    c = get_conn()
    yield c
    c.close()


def rows(conn, source_path):
    cur = conn.cursor()
    cur.execute(
        "SELECT category, service, doc_type, doc_title, section_path, source_url, images "
        "FROM documents WHERE source_path = %s ORDER BY id",
        (source_path,),
    )
    out = cur.fetchall()
    cur.close()
    return out


def test_rebuild_then_skip_then_reingest_on_change(docs_dir, conn):
    import ingest

    assert ingest.run(["--docs-dir", docs_dir, "--rebuild"]) == 0
    got = rows(conn, "Network/VPC/콘솔 사용 가이드.html")
    assert len(got) == 2
    assert got[0][:4] == ("Network", "VPC", "console", "콘솔 사용 가이드")
    assert got[0][4] == "서브넷 생성"
    assert got[0][5] == "https://docs.nhncloud.com/ko/x/"
    assert got[0][6] == [{"path": "Network/VPC/images/s1.png", "caption": "서브넷 생성 버튼을 클릭합니다.", "alt": ""}]
    assert got[1][6] == []

    # 같은 내용이면 건너뛴다 (행 수 그대로)
    assert ingest.run(["--docs-dir", docs_dir]) == 0
    assert len(rows(conn, "Network/VPC/콘솔 사용 가이드.html")) == 2

    # 내용이 바뀌면 그 문서만 다시 적재한다
    path = os.path.join(docs_dir, "Network", "VPC", "콘솔 사용 가이드.html")
    with open(path, "a", encoding="utf-8") as f:
        f.write("<h3>추가</h3><p>추가 본문</p>")
    assert ingest.run(["--docs-dir", docs_dir]) == 0
    got = rows(conn, "Network/VPC/콘솔 사용 가이드.html")
    assert len(got) == 3
    assert got[2][4] == "추가"


def test_questions_table_exists(conn):
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM information_schema.tables WHERE table_name = 'questions'")
    assert cur.fetchone() is not None
    cur.close()
```

- [ ] **Step 2: 실패 확인**

먼저 DB를 띄운다 (Docker Desktop 실행 후):
```bash
docker compose up -d db
```
Run (PowerShell):
```powershell
$env:DB_HOST="localhost"; $env:NVIDIA_API_KEY="<.env 의 값>"; python -m pytest -m integration app/tests/test_ingest_db.py -v
```
Expected: FAIL — `AttributeError: module 'ingest' has no attribute 'run'`

- [ ] **Step 3: `ingest.py`에 실행 흐름 추가**

`app/ingest.py`의 Task 6 코드 **아래에** 이어 붙인다. 상단 import는 아래 표준 라이브러리·psycopg2만 추가한다. **`chunker`, `db`, `llm`은 함수 안에서 import 한다** — `llm`이 최상위에서 `NVIDIA_API_KEY`를 요구하므로, 그래야 단위 테스트가 키 없이 `ingest`를 import 할 수 있다.

```python
import argparse
import hashlib
import json
import sys
from typing import Iterator

from psycopg2.extras import Json


def iter_documents(docs_dir: str) -> Iterator[str]:
    for root, _, files in os.walk(docs_dir):
        for name in sorted(files):
            if name.endswith(".html"):
                rel = os.path.relpath(os.path.join(root, name), docs_dir)
                yield rel.replace("\\", "/")


def load_manifest_urls(docs_dir: str) -> dict[str, str]:
    path = os.path.join(docs_dir, "manifest.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return {e["path"]: e["url"] for e in json.load(f).values() if e.get("path")}


def file_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def existing_hash(cur, source_path: str) -> str | None:
    cur.execute("SELECT content_hash FROM documents WHERE source_path = %s LIMIT 1", (source_path,))
    row = cur.fetchone()
    return row[0] if row else None


def ingest_document(conn, docs_dir: str, rel_path: str, url: str | None) -> int:
    from chunker import chunk_html
    from llm import embed

    with open(os.path.join(docs_dir, rel_path), encoding="utf-8") as f:
        html = f.read()

    category, service, doc_title = split_source_path(rel_path)
    doc_rel_dir = os.path.dirname(rel_path)
    chunks = chunk_html(html, doc_title, doc_rel_dir)
    digest = file_hash(html)

    cur = conn.cursor()
    cur.execute("DELETE FROM documents WHERE source_path = %s", (rel_path,))

    for start in range(0, len(chunks), BATCH_SIZE):
        batch = chunks[start:start + BATCH_SIZE]
        vectors = embed([c.content for c in batch], input_type="passage")
        for chunk, vector in zip(batch, vectors):
            cur.execute(
                """INSERT INTO documents
                   (content, embedding, category, service, doc_type, doc_title,
                    section_path, source_path, source_url, content_hash, images)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (chunk.content, vector, category, service, doc_type_of(doc_title), doc_title,
                 chunk.section_path, rel_path, url, digest,
                 Json([{"path": i.path, "caption": i.caption, "alt": i.alt} for i in chunk.images])),
            )

    conn.commit()   # 문서 단위 커밋: 중간에 끊겨도 앞 문서는 남는다
    cur.close()
    return len(chunks)


def run(argv=None) -> int:
    from db import get_conn, init_schema
    from llm import EMBEDDING_MODEL_NAME, embed_one

    args = parse_args(argv)
    docs_dir = os.path.abspath(args.docs_dir)
    if not os.path.isdir(docs_dir):
        print(f"문서 폴더가 없습니다: {docs_dir}")
        return 1

    urls = load_manifest_urls(docs_dir)
    conn = get_conn()

    dim = len(embed_one("test"))
    print(f"임베딩 모델: {EMBEDDING_MODEL_NAME} (dim={dim}) / 문서 폴더: {docs_dir}")
    init_schema(conn, dim, rebuild=args.rebuild)

    done = skipped = 0
    total_chunks = 0
    failed: list[tuple[str, str]] = []
    cur = conn.cursor()

    for n, rel in enumerate(iter_documents(docs_dir), 1):
        if args.limit and n > args.limit:
            break

        with open(os.path.join(docs_dir, rel), encoding="utf-8") as f:
            digest = file_hash(f.read())
        if not args.rebuild and existing_hash(cur, rel) == digest:
            skipped += 1
            continue

        try:
            count = ingest_document(conn, docs_dir, rel, urls.get(rel))
        except Exception as e:
            conn.rollback()
            failed.append((rel, f"{type(e).__name__}: {e}"))
            print(f"  실패: {rel} — {e}")
            continue

        done += 1
        total_chunks += count
        print(f"[{n}] {rel} → {count} chunks")

    cur.close()
    conn.close()

    print(f"완료: 문서 {done}개 적재, {skipped}개 건너뜀, {len(failed)}개 실패 (청크 {total_chunks}개)")
    for rel, err in failed:
        print(f"  - {rel}: {err}")
    return 1 if failed else 0


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--docs-dir", default=DOCS_DIR)
    p.add_argument("--rebuild", action="store_true", help="documents 테이블을 지우고 전부 다시 적재")
    p.add_argument("--limit", type=int, default=0, help="앞 N개 문서만 (시범용)")
    return p.parse_args(argv)


if __name__ == "__main__":
    sys.exit(run())
```

- [ ] **Step 4: 기존 UI가 새 스키마를 읽도록 `rag.py` 두 곳 수정**

`app/rag.py` `build_bm25()` 안:
```python
    cur.execute("SELECT content, source, service FROM documents")
```
→
```python
    cur.execute("SELECT content, source_path, service FROM documents")
```

`app/rag.py` `hybrid_search()` 안의 벡터 SELECT:
```python
    cur.execute("""
    SELECT content, source, service
      FROM documents
     ORDER BY embedding <-> %s::vector
     LIMIT %s;
    """, (q_vec, top_k))
```
→
```python
    cur.execute("""
    SELECT content, source_path, service
      FROM documents
     ORDER BY embedding <=> %s::vector
     LIMIT %s;
    """, (q_vec, top_k))
```
(`<=>`는 코사인 거리. HNSW 인덱스를 `vector_cosine_ops`로 만들었으므로 연산자를 맞춘다.)

- [ ] **Step 5: 통합 테스트 통과 확인**

Run (PowerShell):
```powershell
$env:DB_HOST="localhost"; $env:NVIDIA_API_KEY="<.env 의 값>"; python -m pytest -m integration app/tests/test_ingest_db.py -v
```
Expected: 2 passed

주의: 이 테스트는 `--rebuild`로 `documents`를 비운다. 지금 들어 있는 3,770행(구 스키마)은 어차피 새 스키마와 맞지 않으므로 사라져도 된다.

- [ ] **Step 6: 시범 수집분 적재와 기존 UI 동작 확인**

Run (PowerShell, `app/`에서):
```powershell
$env:DB_HOST="localhost"; $env:NVIDIA_API_KEY="<.env 의 값>"; $env:DOCS_DIR="..\nhn_cloud_docs_pilot"
python ingest.py --rebuild
```
Expected: `완료: 문서 N개 적재, 0개 건너뜀, 0개 실패`. 실패가 있으면 목록의 원인을 보고 해당 HTML을 확인한다.

Run: 같은 명령을 `--rebuild` 없이 한 번 더.
Expected: `문서 0개 적재, N개 건너뜀`

Run:
```powershell
python -m streamlit run ui.py
```
브라우저에서 `http://localhost:8501` — "VPC에서 서브넷을 만드는 방법"을 질문.
Expected: 오류 없이 답변과 출처(Network/VPC …)가 표시된다. (스크린샷·메뉴 경로 형식은 2단계에서 추가되므로 아직 없음.)

- [ ] **Step 7: compose에 문서 폴더 마운트**

`docker-compose.yaml`의 `app` 서비스에 추가:
```yaml
    environment:
      NVIDIA_API_KEY: ${NVIDIA_API_KEY}
      NVIDIA_LLM_MODEL: ${NVIDIA_LLM_MODEL:-nvidia/nemotron-3-super-120b-a12b}
      NVIDIA_EMBEDDING_MODEL: ${NVIDIA_EMBEDDING_MODEL:-nvidia/nemotron-3-embed-1b}
      DOCS_DIR: /docs
    volumes:
      - ./app:/app
      - ./nhn_cloud_docs:/docs:ro
```
(`version: "3.9"` 줄은 compose가 무시한다고 경고하므로 삭제한다.)

Run: `docker compose config` 
Expected: 오류 없이 병합된 설정이 출력되고 `app.volumes`에 `/docs` 항목이 있다.

- [ ] **Step 8: 커밋**

```bash
git add app/ingest.py app/rag.py app/tests/test_ingest_db.py docker-compose.yaml
git commit -m "feat(ingest): 해시 비교 증분 적재, 문서 단위 커밋, 새 스키마에 기존 UI 호환

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: 서비스 별칭 사전 초안 생성 (`app/aliases.py`)

**Files:**
- Create: `app/aliases.py`
- Modify: `app/requirements.txt` (`pyyaml` 추가)
- Test: `app/tests/test_aliases.py`

**Interfaces:**
- Produces:
  - `alias_variants(service: str) -> list[str]` — 원문, 소문자, 공백 제거, 공백 제거+소문자의 집합을 정렬해 반환. `_`(서비스 없음)는 빈 목록
  - `generate(conn) -> dict[str, list[str]]` — `{"카테고리/서비스": [별칭…]}`, `documents`의 distinct (category, service)에서. `_`는 제외
  - CLI `python aliases.py [--out app/services.generated.yaml]` — YAML로 저장(UTF-8, 키 정렬). 2단계의 서비스 추정이 이 파일과 수동 `services.yaml`을 합쳐 읽는다

- [ ] **Step 1: 실패하는 테스트 작성**

`app/tests/test_aliases.py`:
```python
from aliases import alias_variants, generate


def test_alias_variants_cover_case_and_spacing():
    assert alias_variants("Object Storage") == ["Object Storage", "ObjectStorage", "object storage", "objectstorage"]


def test_alias_variants_single_word_dedupes():
    assert alias_variants("VPC") == ["VPC", "vpc"]


def test_alias_variants_placeholder_is_empty():
    assert alias_variants("_") == []


class FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, sql):
        assert "DISTINCT" in sql

    def fetchall(self):
        return self._rows

    def close(self):
        pass


class FakeConn:
    def __init__(self, rows):
        self.rows = rows

    def cursor(self):
        return FakeCursor(self.rows)


def test_generate_builds_mapping_and_skips_placeholder():
    conn = FakeConn([("Network", "VPC"), ("Storage", "Object Storage"), ("Bill", "_")])
    assert generate(conn) == {
        "Network/VPC": ["VPC", "vpc"],
        "Storage/Object Storage": ["Object Storage", "ObjectStorage", "object storage", "objectstorage"],
    }
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest app/tests/test_aliases.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'aliases'`

- [ ] **Step 3: 구현**

`app/requirements.txt`에 한 줄 추가:
```
pyyaml
```
Run: `python -m pip install pyyaml`

`app/aliases.py`:
```python
"""documents 의 서비스 목록으로 별칭 사전 초안을 만든다.

    python aliases.py                      # app/services.generated.yaml
    python aliases.py --out 다른경로.yaml

여기서 만든 파일은 자동 생성분이다. "NKS", "L7 LB" 같은 약칭은 services.yaml 에
손으로 적고, 검색 단계에서 두 파일을 합쳐 읽는다.
"""

import argparse
import os
import sys

import yaml

from db import get_conn

NO_SERVICE = "_"
DEFAULT_OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "services.generated.yaml")


def alias_variants(service: str) -> list[str]:
    name = service.strip()
    if not name or name == NO_SERVICE:
        return []
    compact = name.replace(" ", "")
    return sorted({name, name.lower(), compact, compact.lower()})


def generate(conn) -> dict[str, list[str]]:
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT category, service FROM documents ORDER BY category, service")
    rows = cur.fetchall()
    cur.close()

    return {
        f"{category}/{service}": alias_variants(service)
        for category, service in rows
        if service != NO_SERVICE
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", default=DEFAULT_OUT)
    args = p.parse_args(argv)

    conn = get_conn()
    mapping = generate(conn)
    conn.close()

    with open(args.out, "w", encoding="utf-8") as f:
        yaml.safe_dump(mapping, f, allow_unicode=True, sort_keys=True)

    print(f"서비스 {len(mapping)}개 → {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest app/tests/test_aliases.py -v`
Expected: 4 passed

- [ ] **Step 5: 시범 데이터로 생성**

Run (PowerShell, `app/`에서): `$env:DB_HOST="localhost"; python aliases.py`
Expected: `서비스 N개 → …services.generated.yaml`. 파일을 열어 `Network/VPC:` 아래에 `- VPC`, `- vpc`가 있는지 확인.

- [ ] **Step 6: 전체 단위 테스트와 커밋**

Run: `python -m pytest -v`
Expected: 단위 테스트 전체 통과 (integration은 제외됨)

```bash
git add app/aliases.py app/requirements.txt app/tests/test_aliases.py app/services.generated.yaml
git commit -m "feat: documents 서비스 목록으로 별칭 사전 초안 생성

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## 완료 기준 (1단계)

- `python -m pytest` 단위 테스트 전체 통과, `-m integration` 2건 통과
- `nhn_cloud_docs_pilot/`에 Network·Bill 문서가 `카테고리/서비스/문서명.html` 구조로 있고 `manifest.json`의 `error`가 0건
- 시범 데이터 적재 후 `python ingest.py` 재실행 시 전부 건너뜀
- `streamlit run ui.py`로 기존 UI가 새 스키마에서 질문·답변 가능
- `app/services.generated.yaml` 생성

2단계 계획(검색·답변·UI·운영·평가)은 이 단계가 끝난 뒤, 시범 데이터의 실제 청크와 별칭 목록을 보고 작성한다. 전체 재수집(26개 카테고리, 1~1.5시간)은 2단계에서 LLM 제공자 확정 후 진행한다.
