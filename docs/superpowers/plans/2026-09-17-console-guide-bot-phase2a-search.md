# 콘솔 안내 챗봇 — 2단계-A: 검색·속도·청커 보강·인프라·전체 재수집 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 질문 이해(의도·서비스) → 한글 2-gram BM25 + 벡터 하이브리드 → 콘솔 가이드 가중치 → 추론 끈 리랭킹(근거 판정 포함)으로 검색 품질과 속도를 올리고, 청커의 이관 결함을 고친 뒤, 26개 카테고리 전체를 재수집·재적재한다.

**Architecture:** 검색은 `rag.py` 안에서 `intent.py`(규칙 기반 의도·서비스 추정), `tokenize_ko.py`(토크나이저), `combine_scores()`(순수 점수 보정)로 나뉜다. 벡터 검색은 2048차원이라 `halfvec` 표현식 HNSW 인덱스를 쓰고(pgvector 0.7+ 이미지로 교체), 리랭킹은 `chat_template_kwargs.enable_thinking=false`로 추론 토큰을 꺼 34초→1초대로 줄인다(실측). 청커는 li/blockquote 안 표·코드를 꺼내 직렬화하고 긴 표를 행 단위로 나눈다. 통합 테스트는 `ragdb_test`로 분리해 실데이터를 지우지 않는다.

**Tech Stack:** Python 3.12, BeautifulSoup4, psycopg2, pgvector(`pgvector/pgvector:pg16`), rank_bm25, openai SDK(NVIDIA NIM), PyYAML, pytest, Selenium

**Spec:** `docs/superpowers/specs/2026-09-17-console-guide-bot-design.md` — 4절(검색) 전체, 3-2·3-3의 이관 항목, 6-2 중 DB 볼륨. 이관 항목 목록: `docs/superpowers/plans/2026-09-17-console-guide-bot-phase2-carryover.md`. 답변 형식·UI·운영·평가(5·6·8-2절)는 2단계-B 계획.

## Global Constraints

- Python 3.12; `python` 은 `%LOCALAPPDATA%\Programs\Python\Python312\python.exe`. Korean 출력 시 `PYTHONIOENCODING=utf-8`.
- 호스트에서 DB 접근 시 `DB_HOST=localhost`. NVIDIA 키는 `.env`의 `NVIDIA_API_KEY`에서 읽어 export (어디에도 붙여넣지 않음).
- 통합 테스트(`-m integration`)는 **`ragdb_test`** 데이터베이스만 쓴다. 실데이터 DB(`ragdb`)를 지우는 테스트는 금지.
- 청크 최대 1,500자, 헤더 줄·마커 줄도 길이에 계상. 긴 표/코드 블록은 줄 단위로 나누고 첫 줄을 반복.
- 스크린샷 마커 `[스크린샷 N: caption 앞 60자]`, 캡션은 한 줄. `Image.missing` 은 크롤러의 `data-missing="true"`.
- 의도 `console | general`, 서비스 키는 `"카테고리/서비스"`. 서비스 매칭은 필터가 아니라 부스트. 여러 별칭이 걸리면 가장 긴 별칭 우선.
- 점수 보정: `doc_type == console` 이고 의도 `console` → ×1.5, 서비스 일치 → ×1.3, 벡터·BM25 모두 등장 → ×1.2. 리랭킹 후보 12개, 문서당 900자.
- LLM 호출은 질문당 2회(리랭킹 1 + 답변 1). 리랭킹은 추론 끔(`extra_body={"chat_template_kwargs": {"enable_thinking": False}}`).
- 벡터 검색은 코사인(`<=>`). 차원 > 2000 이면 `halfvec(dim)` 표현식 인덱스와 같은 표현식으로 질의.
- 테스트 파일은 `app/tests/`·`crawlling/tests/`에 `__init__.py` 없이, 파일명은 저장소 전체에서 고유.
- 커밋 메시지 끝: `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`. `.env`, `nhn_cloud_docs*/`, `app/data/` 는 커밋 금지.
- 기존 UI(`app/ui.py`)는 각 태스크 후에도 `streamlit run ui.py` 로 동작해야 한다(2단계-B 전까지 형식은 그대로).

---

## 파일 구조

| 파일 | 상태 | 책임 |
|---|---|---|
| `docker-compose.yaml` | 수정 | `pgvector/pgvector:pg16` + named volume |
| `app/db.py` | 수정 | `_embedding_dim` 공개(`embedding_dim`), 차원별 HNSW/halfvec 인덱스 |
| `app/tests/test_ingest_db.py` | 수정 | `ragdb_test` 사용 |
| `app/chunker.py` | 재작성 | 중첩 표/코드, 긴 블록 분할, 헤더 계상, `Image.missing`, `has_breadcrumb` |
| `app/ingest.py` | 수정 | manifest 브레드크럼 전달, 전체 실행 시 사라진 문서 정리 |
| `app/tokenize_ko.py` | 신규 | 한글 2-gram + 영숫자 토크나이저 |
| `app/intent.py` | 신규 | 의도 판정, 별칭 로드, 서비스 추정 |
| `app/services.yaml` | 신규 | 수동 별칭 |
| `app/rag.py` | 수정 | `Candidate`, 차원 인식 벡터 질의, 토크나이저 BM25, `combine_scores`, 추론 끈 리랭킹 + 근거 판정 |
| `app/llm.py` | 수정 | `chat(..., think=True)` |
| `app/ui.py` | 최소 수정 | 새 검색 인터페이스에 맞춤 |
| `eval/bench_latency.py` | 신규 | 동시 1/3/6 지연·재시도 측정 |
| `README.md` | 수정 | 재수집 결과·측정치·새 옵션 |

---

### Task 1: 인프라 — pgvector 0.7+, halfvec 인덱스, 테스트 DB 분리

**Files:**
- Modify: `docker-compose.yaml`
- Modify: `app/db.py`
- Modify: `app/rag.py` (`build_bm25`, `hybrid_search`의 벡터 SELECT)
- Modify: `app/tests/test_ingest_db.py`

**Interfaces:**
- Consumes: 기존 `db.init_schema(conn, dim, rebuild)`, `db._embedding_dim(cur)`
- Produces:
  - `db.embedding_dim(conn) -> int | None` — 현재 `documents.embedding` 차원(테이블 없으면 None)
  - `db.vector_order_by(dim: int) -> str` — `"embedding <=> %s::vector"` 또는 `"(embedding::halfvec({dim})) <=> %s::halfvec({dim})"`
  - `rag.EMBED_DIM: int` — `build_bm25()`가 DB에서 읽어 설정
  - 통합 테스트 픽스처 `test_db` — `ragdb_test`를 만들고 `db.DB_NAME`을 바꿔 준다

- [ ] **Step 1: compose 이미지·볼륨 교체**

`docker-compose.yaml`의 `db` 서비스를 다음으로 바꾼다 (`app` 서비스는 그대로):
```yaml
services:
  db:
    image: pgvector/pgvector:pg16
    container_name: pgvector
    environment:
      POSTGRES_DB: ragdb
      POSTGRES_USER: devops
      POSTGRES_PASSWORD: devops
    volumes:
      - pgdata:/var/lib/postgresql/data
    ports:
      - "5432:5432"
```
파일 맨 아래에 추가:
```yaml
volumes:
  pgdata:
```

Run: `docker compose up -d --force-recreate db` 후 `docker exec pgvector psql -U devops -d ragdb -tAc "CREATE EXTENSION IF NOT EXISTS vector; SELECT extversion FROM pg_extension WHERE extname='vector';"`
Expected: `0.7.x` 이상 (halfvec 지원). 기존 컨테이너의 시범 데이터는 사라진다 — Task 1 끝에서 다시 적재한다.

- [ ] **Step 2: 통합 테스트를 `ragdb_test`로 옮기는 실패 테스트**

`app/tests/test_ingest_db.py` 상단(기존 `conn` 픽스처 위)에 추가하고, 기존 `conn` 픽스처가 `test_db`에 의존하게 바꾼다:
```python
@pytest.fixture(scope="module")
def test_db():
    """실데이터 DB(ragdb)를 건드리지 않도록 ragdb_test 를 만들고 그쪽으로 연결을 돌린다."""
    import psycopg2
    import db

    admin = psycopg2.connect(host=db.DB_HOST, port=db.DB_PORT, database=db.DB_NAME,
                             user=db.DB_USER, password=db.DB_PASSWORD)
    admin.autocommit = True
    cur = admin.cursor()
    cur.execute("SELECT 1 FROM pg_database WHERE datname = 'ragdb_test'")
    if cur.fetchone() is None:
        cur.execute("CREATE DATABASE ragdb_test")
    cur.close()
    admin.close()

    original = db.DB_NAME
    db.DB_NAME = "ragdb_test"
    yield "ragdb_test"
    db.DB_NAME = original


@pytest.fixture
def conn(test_db):
    from db import get_conn
    c = get_conn()
    yield c
    c.close()


def test_uses_test_database(conn):
    cur = conn.cursor()
    cur.execute("SELECT current_database()")
    assert cur.fetchone()[0] == "ragdb_test"
    cur.close()
```
기존 `conn` 픽스처 정의는 삭제한다(위 것으로 대체). `test_rebuild_then_skip_then_reingest_on_change` 와 `test_questions_table_exists` 는 그대로 둔다 — `ingest.run()` 은 함수 안에서 `from db import get_conn` 을 하므로 바뀐 `db.DB_NAME` 을 따른다.

- [ ] **Step 3: 실패 확인**

Run (PowerShell, 루트에서): `$env:DB_HOST="localhost"; $env:NVIDIA_API_KEY="<.env 값>"; python -m pytest -m integration app/tests/test_ingest_db.py -v`
Expected: `test_uses_test_database` PASS 여부와 무관하게 이 단계에서는 실행이 되는지만 본다. (아직 `db.py` 변경 전이라 HNSW 경고가 나오지만 테스트는 통과할 수 있다 — 다음 단계에서 인덱스 생성이 실제로 성공하는지 확인한다.)

- [ ] **Step 4: `db.py` — 차원별 인덱스와 공개 헬퍼**

`app/db.py`에서 `_embedding_dim` 아래에 추가:
```python
def embedding_dim(conn) -> int | None:
    """documents.embedding 의 선언 차원. 테이블이 없으면 None."""
    cur = conn.cursor()
    try:
        if not _table_exists(cur, "documents"):
            return None
        return _embedding_dim(cur)
    finally:
        cur.close()


HALFVEC_THRESHOLD = 2000   # pgvector 의 vector HNSW 상한. 넘으면 halfvec 표현식 인덱스를 쓴다.


def vector_order_by(dim: int) -> str:
    """벡터 검색 ORDER BY 식. 인덱스를 만든 표현식과 똑같아야 인덱스를 탄다."""
    if dim > HALFVEC_THRESHOLD:
        return f"(embedding::halfvec({dim})) <=> %s::halfvec({dim})"
    return "embedding <=> %s::vector"
```
`init_schema` 안의 HNSW 블록을 다음으로 교체:
```python
    # vector 타입 HNSW 는 2000차원까지. 그 이상은 halfvec 표현식 인덱스(pgvector 0.7+).
    cur.execute("SAVEPOINT hnsw;")
    try:
        if dim > HALFVEC_THRESHOLD:
            cur.execute(
                "CREATE INDEX IF NOT EXISTS documents_embedding_hnsw "
                f"ON documents USING hnsw ((embedding::halfvec({dim})) halfvec_cosine_ops);"
            )
        else:
            cur.execute(
                "CREATE INDEX IF NOT EXISTS documents_embedding_hnsw "
                "ON documents USING hnsw (embedding vector_cosine_ops);"
            )
    except psycopg2.Error as e:
        cur.execute("ROLLBACK TO SAVEPOINT hnsw;")
        print(f"  [경고] HNSW 인덱스를 만들지 못했습니다 (pgvector 0.7 이상 필요): {str(e).strip()}")
```

- [ ] **Step 5: `rag.py` — 차원 인식 벡터 질의**

`app/rag.py` 상단 import 를 `from db import get_conn, embedding_dim, vector_order_by` 로 바꾸고, 전역에 `EMBED_DIM = 0` 을 추가한다. `build_bm25()` 의 `global` 줄을 `global bm25, bm25_corpus, EMBED_DIM` 으로 바꾸고 `conn = get_conn()` 바로 다음에 `EMBED_DIM = embedding_dim(conn) or 0` 을 넣는다. `hybrid_search()` 의 벡터 SELECT 를 다음으로 바꾼다:
```python
    cur.execute(f"""
    SELECT content, source_path, service
      FROM documents
     ORDER BY {vector_order_by(EMBED_DIM)}
     LIMIT %s;
    """, (q_vec, top_k))
```
(Task 6에서 이 함수를 다시 고친다. 여기서는 인덱스와 식을 맞추는 것만.)

- [ ] **Step 6: 시범 데이터 재적재와 인덱스 확인**

Run (PowerShell, `app/`에서): `$env:DB_HOST="localhost"; $env:NVIDIA_API_KEY="<.env 값>"; $env:DOCS_DIR="..\nhn_cloud_docs_pilot"; $env:PYTHONIOENCODING="utf-8"; python ingest.py --rebuild`
Expected: `완료: 문서 60개 적재 … (청크 1519개)`, **HNSW 경고 없음**.

Run: `docker exec pgvector psql -U devops -d ragdb -tAc "SELECT indexdef FROM pg_indexes WHERE indexname='documents_embedding_hnsw'"`
Expected: `... USING hnsw (((embedding)::halfvec(2048)) halfvec_cosine_ops)`

Run: `docker exec pgvector psql -U devops -d ragdb -c "EXPLAIN SELECT content FROM documents ORDER BY (embedding::halfvec(2048)) <=> (SELECT embedding::halfvec(2048) FROM documents LIMIT 1) LIMIT 5"`
Expected: 계획에 `Index Scan using documents_embedding_hnsw` 포함.

- [ ] **Step 7: 통합 테스트 통과와 실데이터 보존 확인**

Run: `$env:DB_HOST="localhost"; $env:NVIDIA_API_KEY="<.env 값>"; python -m pytest -m integration app/tests/test_ingest_db.py -v`
Expected: 3 passed.
Run: `docker exec pgvector psql -U devops -d ragdb -tAc "SELECT count(*) FROM documents"`
Expected: `1519` (테스트가 실데이터를 지우지 않았다).

- [ ] **Step 8: 단위 테스트와 커밋**

Run: `python -m pytest -q` → 전체 통과.
```bash
git add docker-compose.yaml app/db.py app/rag.py app/tests/test_ingest_db.py
git commit -m "feat(db): pgvector 0.7 이미지·볼륨, 2048차원 halfvec 인덱스, 통합 테스트 DB 분리

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: 청커 보강 — 중첩 표/코드, 긴 블록 분할, 헤더 계상, `Image.missing`, `has_breadcrumb`

**Files:**
- Modify: `app/chunker.py` (전체 교체)
- Test: `app/tests/test_chunker.py` (추가)

**Interfaces:**
- Produces:
  - `Image(path, caption, alt="", missing=False)`
  - `chunk_html(html, doc_title, doc_rel_dir, max_chars=1500, has_breadcrumb=None) -> list[Chunk]` — `has_breadcrumb=True`면 첫 h2를 무조건 브레드크럼으로, `False`면 절대 아닌 것으로, `None`이면 기존 휴리스틱(`>` 포함)
  - 나머지 이름(`Chunk`, `table_to_text`)은 그대로

- [ ] **Step 1: 실패하는 테스트 추가**

`app/tests/test_chunker.py` 끝에 추가:
```python
def test_nested_table_in_list_item_is_serialized_separately():
    html = ('<section><h3>A</h3><ul><li>항목 설명'
            '<table><tr><th>이름</th><th>값</th></tr><tr><td>a</td><td>1</td></tr></table>'
            '</li></ul></section>')
    c = chunk_html(html, "t", "C/S")[0]
    assert "항목 설명\n이름 | 값\n이름: a | 값: 1" in c.content
    assert c.content.count("이름: a") == 1


def test_nested_pre_in_blockquote_keeps_code_marker():
    html = '<section><h3>A</h3><blockquote>참고 <pre>curl -X GET /x</pre></blockquote></section>'
    c = chunk_html(html, "t", "C/S")[0]
    assert "참고\n[코드]\ncurl -X GET /x" in c.content


def test_image_inside_nested_table_uses_cell_caption_and_list_text_is_not_duplicated():
    html = ('<section><h3>A</h3><li>설명<table><tr><td>로그인 화면 <img src="./images/l.png"/></td></tr></table></li></section>')
    c = chunk_html(html, "t", "C/S")[0]
    assert c.images[0].caption == "로그인 화면"
    assert c.content.count("로그인 화면") == 2      # 셀 텍스트 1회 + 마커 1회


def test_long_table_is_split_by_rows_with_header_repeated():
    rows = "".join(f"<tr><td>키{i}</td><td>{'값' * 60}</td></tr>" for i in range(30))
    html = f'<section><h3>표</h3><table><tr><th>이름</th><th>설명</th></tr>{rows}</table></section>'
    result = chunk_html(html, "t", "C/S", max_chars=800)
    assert len(result) >= 3
    for c in result:
        assert c.content.startswith("t > 표\n이름 | 설명\n")
        assert len(c.content) <= 800 + len("t > 표\n이름 | 설명\n")
    assert sum(c.content.count("이름: 키") for c in result) == 30


def test_header_and_marker_lines_count_toward_limit():
    body = "가" * 700
    html = f'<section><h3>절</h3><p>{body}</p><p>{body} <img src="./images/a.png"></p></section>'
    result = chunk_html(html, "t", "C/S", max_chars=1450)
    assert len(result) == 2          # 700+700 자체는 1,400 이지만 헤더·마커 줄을 더하면 넘는다


def test_missing_flag_from_crawler_attribute():
    html = '<section><h3>A</h3><p>본문 <img src="https://x/y.png" data-missing="true"></p></section>'
    img = chunk_html(html, "t", "C/S")[0].images[0]
    assert img.missing is True and img.path == "https://x/y.png"


def test_has_breadcrumb_false_keeps_heading_with_gt():
    html = '<section><h2>Network &gt; Subnet 메뉴 안내</h2><p>본문</p></section>'
    assert chunk_html(html, "t", "C/S", has_breadcrumb=False)[0].section_path == "Network > Subnet 메뉴 안내"


def test_has_breadcrumb_true_drops_first_h2_even_without_gt():
    html = '<section><h2>브레드크럼 없음</h2><h3>A</h3><p>본문</p></section>'
    result = chunk_html(html, "t", "C/S", has_breadcrumb=True)
    assert [c.section_path for c in result] == ["A"]
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest app/tests/test_chunker.py -v`
Expected: 새 테스트 8개 FAIL (기존 16개는 PASS 유지).

- [ ] **Step 3: `app/chunker.py` 전체 교체**

```python
"""HTML 문서를 섹션 단위 청크로 바꾼다.

NHN Cloud 콘솔 가이드는 h3/h4 하나가 작업 단계 묶음이고, 스크린샷은 대부분 설명 문단
바로 뒤의 빈 문단(<p><img/></p>)에 온다. 그래서 섹션을 청크 단위로 삼고, 이미지는 자기가
속한 블록의 텍스트를, 그 블록이 비어 있으면 직전 텍스트 블록을 캡션으로 잡는다.
li/blockquote 안에 중첩된 표·코드는 꺼내어 별도 블록으로 직렬화한다 (평문으로 뭉개지지 않게).
"""

from dataclasses import dataclass, field

from bs4 import BeautifulSoup

MAX_CHARS = 1500
CAPTION_CHARS = 60

HEADING_LEVELS = {"h2": 2, "h3": 3, "h4": 4}
BLOCK_TAGS = ["h2", "h3", "h4", "h5", "h6", "p", "li", "pre", "table", "blockquote", "img"]
# 다른 블록 안에 중첩돼 있어도 따로 직렬화해야 하는 태그
NESTED_BLOCKS = ["table", "pre"]


@dataclass
class Image:
    path: str
    caption: str
    alt: str = ""
    missing: bool = False


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


def _caption_for(img, el, text: str, last_text: str) -> str:
    """표 안 이미지는 감싸는 셀 텍스트, 그 외는 블록 텍스트, 블록이 비어 있으면 직전 텍스트."""
    if el.name == "table":
        cell = img.find_parent(["td", "th"])
        cell_text = cell.get_text(" ", strip=True) if cell is not None else ""
        if cell_text:
            return cell_text
    return text if text else last_text


def _image(img, caption: str, doc_rel_dir: str) -> Image:
    src = (img.get("src") or "").strip()
    if src.startswith("./"):
        path = f"{doc_rel_dir}/{src[2:]}"
    elif src.startswith(("http://", "https://")):
        path = src
    else:
        path = f"{doc_rel_dir}/{src}"
    return Image(
        path=path,
        caption=" ".join(caption.split()),
        alt=img.get("alt") or "",
        missing=(img.get("data-missing") == "true"),
    )


def _marker(index: int, image: Image) -> str:
    return f"[스크린샷 {index}: {image.caption[:CAPTION_CHARS]}]"


def _section_path(stack: dict[int, str]) -> str:
    return " > ".join(stack[level] for level in (2, 3, 4) if stack[level])


def _split_long_block(text: str, images: list[Image], max_chars: int) -> list[tuple[str, list[Image]]]:
    """한 블록이 max_chars 를 넘고 여러 줄이면 줄 단위로 나눈다.

    표는 헤더 행, 코드는 '[코드]' 가 첫 줄이므로 첫 줄을 조각마다 반복해 각 조각이
    스스로를 설명하게 한다. 이미지는 첫 조각에만 붙인다.
    """
    lines = text.split("\n")
    if len(text) <= max_chars or len(lines) < 2:
        return [(text, images)]

    head, rest = lines[0], lines[1:]
    pieces: list[str] = []
    current = [head]
    length = len(head)
    for line in rest:
        if len(current) > 1 and length + len(line) + 1 > max_chars:
            pieces.append("\n".join(current))
            current, length = [head], len(head)
        current.append(line)
        length += len(line) + 1
    pieces.append("\n".join(current))

    return [(piece, images if i == 0 else []) for i, piece in enumerate(pieces)]


def _build_chunks(doc_title: str, section_path: str, blocks: list[tuple[str, list[Image]]], max_chars: int) -> list[Chunk]:
    header = f"{doc_title} > {section_path}" if section_path else doc_title

    expanded = [piece for text, images in blocks for piece in _split_long_block(text, images, max_chars)]

    pieces: list[list[tuple[str, list[Image]]]] = []
    current: list[tuple[str, list[Image]]] = []
    length = len(header) + 1
    for text, images in expanded:
        size = (len(text) + 1 if text else 0) + sum(len(_marker(9, im)) + 1 for im in images)
        if current and length + size > max_chars:
            pieces.append(current)
            current, length = [], len(header) + 1
        current.append((text, images))
        length += size
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
                lines.append(_marker(len(images), image))
        chunks.append(Chunk(content="\n".join(lines), section_path=section_path, images=images))
    return chunks


def chunk_html(html: str, doc_title: str, doc_rel_dir: str, max_chars: int = MAX_CHARS,
               has_breadcrumb: bool | None = None) -> list[Chunk]:
    soup = BeautifulSoup(html, "html.parser")

    # 첫 h2 가 브레드크럼이면 메타데이터일 뿐이므로 본문에서 뺀다. manifest 가 알려주면 그 값을 믿는다.
    first_h2 = soup.find("h2")
    if first_h2 is not None:
        is_crumb = has_breadcrumb if has_breadcrumb is not None else (">" in first_h2.get_text(" ", strip=True))
        if is_crumb:
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

    def emit(el):
        nonlocal last_text
        if el.name == "img":
            text, images = "", [_image(el, last_text, doc_rel_dir)]
        else:
            text = _block_text(el)
            images = [_image(img, _caption_for(img, el, text, last_text), doc_rel_dir) for img in el.find_all("img")]
        if not text and not images:
            return
        if text:
            last_text = text
        blocks.append((text, images))

    # find_all 은 문서 순서라 상위 블록이 먼저 온다. 상위가 처리한 요소의 하위는 건너뛴다.
    for el in soup.find_all(BLOCK_TAGS):
        if id(el) in consumed or any(id(p) in consumed for p in el.parents):
            continue
        consumed.add(id(el))

        level = HEADING_LEVELS.get(el.name)
        if level:
            flush()
            stack[level] = el.get_text(" ", strip=True)
            for deeper in range(level + 1, 5):
                stack[deeper] = ""
            last_text = stack[level]
            continue

        # li/blockquote/p 안의 표·코드는 꺼내서 뒤에 따로 직렬화한다.
        nested = [] if el.name in NESTED_BLOCKS or el.name == "img" else el.find_all(NESTED_BLOCKS)
        for inner in nested:
            inner.extract()
            consumed.add(id(inner))

        emit(el)
        for inner in nested:
            emit(inner)

    flush()

    return [
        chunk
        for section_path, section_blocks in sections
        for chunk in _build_chunks(doc_title, section_path, section_blocks, max_chars)
    ]
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest app/tests/test_chunker.py -v`
Expected: 24 passed (기존 16 + 신규 8). 기존 테스트가 깨지면 새 코드를 고친다 — 기존 테스트를 바꾸지 않는다. 특히 `test_long_section_splits_at_block_boundary_with_header_on_each_piece`(3조각)와 `test_caption_is_normalized_to_one_line`이 그대로 통과해야 한다.

- [ ] **Step 5: 시범 코퍼스로 회귀 확인**

Run (`app/`에서, `PYTHONIOENCODING=utf-8`):
```bash
python -c "
import os, glob, io, sys; sys.path.insert(0, os.getcwd()); import chunker
root = os.path.abspath('../nhn_cloud_docs_pilot'); n = imgs = over = 0
for p in glob.glob(root + '/**/*.html', recursive=True):
    rel = os.path.relpath(p, root).replace(chr(92), '/')
    for c in chunker.chunk_html(io.open(p, encoding='utf-8').read(), os.path.splitext(os.path.basename(rel))[0], os.path.dirname(rel)):
        n += 1; imgs += len(c.images); over += len(c.content) > 1500
print('chunks', n, 'images', imgs, 'over1500', over)
"
```
Expected: `images 37`, `over1500` 이 이전(52)보다 크게 줄고 0에 가깝다(한 줄이 1,500자를 넘는 블록만 남는다). 청크 수는 1,519 안팎에서 늘 수 있다.

- [ ] **Step 6: 커밋**

```bash
git add app/chunker.py app/tests/test_chunker.py
git commit -m "feat(chunker): 중첩 표·코드 직렬화, 긴 블록 행 분할, 헤더 길이 계상, missing 플래그, has_breadcrumb

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: ingest — manifest 브레드크럼 전달, 사라진 문서 정리

**Files:**
- Modify: `app/ingest.py`
- Test: `app/tests/test_ingest_helpers.py`(추가), `app/tests/test_ingest_db.py`(추가)

**Interfaces:**
- Consumes: Task 2 `chunk_html(..., has_breadcrumb=...)`
- Produces:
  - `load_manifest(docs_dir) -> dict[str, tuple[str | None, bool]]` — `{상대경로: (url, has_breadcrumb)}` (`load_manifest_urls` 대체)
  - `ingest_document(conn, docs_dir, rel_path, url, has_breadcrumb) -> int`
  - `prune_missing(conn, seen_paths: list[str]) -> int` — 디스크에 없는 `source_path` 행 삭제, 삭제 문서 수 반환. `run()`은 `--limit` 없이 전체를 돌았을 때만 호출

- [ ] **Step 1: 실패하는 테스트**

`app/tests/test_ingest_helpers.py` 끝에 추가:
```python
import json


def test_load_manifest_gives_url_and_breadcrumb_flag(tmp_path):
    from ingest import load_manifest
    (tmp_path / "manifest.json").write_text(json.dumps({
        "https://d/a": {"path": "A/B/c.html", "url": "https://d/a", "breadcrumb": ["A", "B", "c"], "status": "ok"},
        "https://d/b": {"path": "A/_/d.html", "url": "https://d/b", "breadcrumb": [], "status": "no_breadcrumb"},
    }), encoding="utf-8")
    m = load_manifest(str(tmp_path))
    assert m["A/B/c.html"] == ("https://d/a", True)
    assert m["A/_/d.html"] == ("https://d/b", False)
    assert load_manifest(str(tmp_path / "없음")) == {}
```
`app/tests/test_ingest_db.py` 끝에 추가:
```python
def test_prune_removes_rows_for_deleted_files(docs_dir, conn):
    import ingest, os

    assert ingest.run(["--docs-dir", docs_dir, "--rebuild"]) == 0
    # 두 번째 문서를 추가 적재한 뒤 파일을 지우면, 다음 전체 실행이 그 행을 정리한다
    extra = os.path.join(docs_dir, "Network", "VPC", "개요.html")
    with open(extra, "w", encoding="utf-8") as f:
        f.write("<section><h2>Network &gt; VPC &gt; 개요</h2><h3>소개</h3><p>VPC 개요 본문</p></section>")
    assert ingest.run(["--docs-dir", docs_dir]) == 0
    assert len(rows(conn, "Network/VPC/개요.html")) == 1

    os.remove(extra)
    assert ingest.run(["--docs-dir", docs_dir]) == 0
    assert rows(conn, "Network/VPC/개요.html") == []
    assert len(rows(conn, "Network/VPC/콘솔 사용 가이드.html")) == 2   # 남아 있는 문서는 그대로
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest app/tests/test_ingest_helpers.py -v` → `ImportError: cannot import name 'load_manifest'`.

- [ ] **Step 3: 구현**

`app/ingest.py`에서 `load_manifest_urls` 를 다음으로 교체:
```python
def load_manifest(docs_dir: str) -> dict[str, tuple[str | None, bool]]:
    """{상대 경로: (원본 URL, 브레드크럼 있음)}. manifest 가 없으면 {}."""
    path = os.path.join(docs_dir, "manifest.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        entries = json.load(f).values()
    return {
        e["path"]: (e.get("url"), bool(e.get("breadcrumb")))
        for e in entries if e.get("path")
    }
```
`ingest_document` 시그니처를 `def ingest_document(conn, docs_dir, rel_path, url, has_breadcrumb=None) -> int:` 로 바꾸고 `chunk_html(html, doc_title, doc_rel_dir)` 호출을 `chunk_html(html, doc_title, doc_rel_dir, has_breadcrumb=has_breadcrumb)` 로 바꾼다.

`existing_hash` 아래에 추가:
```python
def prune_missing(conn, seen_paths: list[str]) -> int:
    """디스크에 더 이상 없는 문서의 행을 지운다. 지운 문서 수를 돌려준다."""
    cur = conn.cursor()
    try:
        cur.execute("SELECT DISTINCT source_path FROM documents")
        stale = [row[0] for row in cur.fetchall() if row[0] not in set(seen_paths)]
        if stale:
            cur.execute("DELETE FROM documents WHERE source_path = ANY(%s)", (stale,))
        conn.commit()
        return len(stale)
    finally:
        cur.close()
```
`run()` 안: `urls = load_manifest_urls(docs_dir)` → `manifest = load_manifest(docs_dir)`; 루프 앞에 `seen: list[str] = []`; 루프에서 `--limit` 검사 다음, 해시 검사 전에 `seen.append(rel)`; `ingest_document(conn, docs_dir, rel, urls.get(rel))` → `url, has_crumb = manifest.get(rel, (None, None)); count = ingest_document(conn, docs_dir, rel, url, has_crumb)`; 루프가 끝난 뒤 `cur.close()` 전에:
```python
    pruned = 0
    if not args.limit:
        pruned = prune_missing(conn, seen)
```
완료 메시지를 `print(f"완료: 문서 {done}개 적재, {skipped}개 건너뜀, {len(failed)}개 실패, {pruned}개 정리 (청크 {total_chunks}개)")` 로.

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest -q` (단위) → 통과. Run (PowerShell, DB_HOST·키 설정): `python -m pytest -m integration app/tests/test_ingest_db.py -v` → 4 passed.

- [ ] **Step 5: 커밋**

```bash
git add app/ingest.py app/tests/test_ingest_helpers.py app/tests/test_ingest_db.py
git commit -m "feat(ingest): manifest 브레드크럼 여부 전달, 전체 실행 시 사라진 문서 행 정리

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: 한글 2-gram 토크나이저와 BM25 적용

**Files:**
- Create: `app/tokenize_ko.py`
- Modify: `app/rag.py` (`build_bm25`, `hybrid_search`의 BM25 부분)
- Test: `app/tests/test_tokenize_ko.py`

**Interfaces:**
- Produces: `tokenize(text: str) -> list[str]` — 영숫자(`.`, `-`, `_` 포함) 토큰은 소문자 그대로, 한글 연속 구간은 2-gram(길이 1이면 그대로). 그 외 문자는 버림.

- [ ] **Step 1: 실패하는 테스트**

`app/tests/test_tokenize_ko.py`:
```python
from rank_bm25 import BM25Okapi

from tokenize_ko import tokenize


def test_hangul_bigrams_bridge_particles():
    assert tokenize("인스턴스를 생성") == ["인스", "스턴", "턴스", "스를", "생성"]
    assert tokenize("인스턴스 생성") == ["인스", "스턴", "턴스", "생성"]


def test_ascii_tokens_lowercased_and_kept_whole():
    assert tokenize("VPC 서브넷 v2.0 API") == ["vpc", "서브", "브넷", "v2.0", "api"]


def test_single_hangul_char_kept():
    assert tokenize("표 생성") == ["표", "생성"]


def test_punctuation_dropped():
    assert tokenize("로드 밸런서(DSR)를 만들까?") == ["로드", "밸런", "런서", "dsr", "를", "만들", "들까"]


def test_bm25_with_bigrams_matches_inflected_query():
    docs = ["인스턴스 생성 버튼을 클릭합니다", "오브젝트 스토리지 컨테이너를 만듭니다"]
    bm25 = BM25Okapi([tokenize(d) for d in docs])
    scores = bm25.get_scores(tokenize("인스턴스를 생성하려면"))
    assert scores[0] > scores[1] > 0 or (scores[0] > 0 and scores[1] == 0)
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest app/tests/test_tokenize_ko.py -v` → `ModuleNotFoundError: No module named 'tokenize_ko'`.

- [ ] **Step 3: 구현**

`app/tokenize_ko.py`:
```python
"""BM25 용 토크나이저.

공백 분리는 "인스턴스를"과 "인스턴스"를 다른 토큰으로 봐서 조사만 붙어도 못 찾는다.
형태소 분석기 없이 한글은 2-gram 으로 쪼개고, 영숫자(버전·API 이름)는 통째로 소문자화한다.
"""

import re

_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*|[가-힣]+")


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for tok in _TOKEN.findall(text):
        if "가" <= tok[0] <= "힣":
            if len(tok) == 1:
                tokens.append(tok)
            else:
                tokens.extend(tok[i:i + 2] for i in range(len(tok) - 1))
        else:
            tokens.append(tok.lower())
    return tokens
```
`app/rag.py`: `from tokenize_ko import tokenize` 를 추가하고, `build_bm25()`의 `tokenized = [doc.split() for doc in bm25_corpus]` → `tokenized = [tokenize(doc) for doc in bm25_corpus]`, `hybrid_search()`의 `tokenized_query = query.split()` → `tokenized_query = tokenize(query)`.

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest app/tests/test_tokenize_ko.py -v` → 5 passed. `python -m pytest -q` → 전체 통과.

- [ ] **Step 5: 커밋**

```bash
git add app/tokenize_ko.py app/tests/test_tokenize_ko.py app/rag.py
git commit -m "feat(search): 한글 2-gram 토크나이저로 BM25 재현율 개선

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: 질문 이해 — 의도 판정, 별칭 사전, 서비스 추정

**Files:**
- Create: `app/intent.py`, `app/services.yaml`
- Test: `app/tests/test_intent.py`

**Interfaces:**
- Produces:
  - `detect_intent(question: str) -> str` — `"console"` | `"general"`
  - `load_aliases(generated_path=None, manual_path=None) -> dict[str, str]` — `{별칭(소문자): "카테고리/서비스"}`. 기본 경로는 `app/services.generated.yaml`, `app/services.yaml`. 수동 파일이 같은 별칭을 정의하면 수동이 이긴다. 파일이 없으면 그 쪽은 건너뜀
  - `detect_service(question: str, aliases: dict[str, str], fallback: str | None = None) -> str | None` — 질문(소문자)에 포함된 별칭 중 **가장 긴 것**의 서비스, 없으면 `fallback`
  - `CONSOLE_HINTS: tuple[str, ...]`

- [ ] **Step 1: 실패하는 테스트**

`app/tests/test_intent.py`:
```python
import pytest

from intent import CONSOLE_HINTS, detect_intent, detect_service, load_aliases


@pytest.mark.parametrize("q", [
    "VPC에 서브넷을 만드는 방법", "로드 밸런서는 어디서 설정해?", "인스턴스 생성 버튼이 안 보여",
    "플로팅 IP를 연결하려면 어떻게 해", "콘솔에서 키페어 등록", "NAT 게이트웨이 삭제하는 법",
    "보안 그룹 규칙 추가", "화면에서 DNS 레코드 변경", "오브젝트 스토리지 컨테이너 생성 절차", "알림 수신자 등록은 어떻게",
])
def test_console_intent(q):
    assert detect_intent(q) == "console"


@pytest.mark.parametrize("q", [
    "VPC와 서브넷의 차이가 뭐야", "SMS API 요청 파라미터 알려줘", "오브젝트 스토리지 요금 체계",
    "로드 밸런서 헬스체크 기준값", "리전이 몇 개야", "API 인증 토큰 유효기간", "릴리스 노트 최근 변경사항",
    "NAT 게이트웨이 대역폭 제한", "Terraform 프로바이더 지원 여부", "SLA 보장 수준",
])
def test_general_intent(q):
    assert detect_intent(q) == "general"


def test_console_hints_are_nonempty_tuple():
    assert isinstance(CONSOLE_HINTS, tuple) and "콘솔" in CONSOLE_HINTS


def test_load_aliases_merges_generated_and_manual(tmp_path):
    gen = tmp_path / "gen.yaml"
    gen.write_text("Network/VPC:\n- VPC\n- vpc\nStorage/Object Storage:\n- Object Storage\n", encoding="utf-8")
    man = tmp_path / "man.yaml"
    man.write_text("Network/Load Balancer:\n- LB\n- 로드밸런서\nNetwork/VPC:\n- 브이피씨\n", encoding="utf-8")
    aliases = load_aliases(str(gen), str(man))
    assert aliases["vpc"] == "Network/VPC"
    assert aliases["object storage"] == "Storage/Object Storage"
    assert aliases["lb"] == "Network/Load Balancer"
    assert aliases["브이피씨"] == "Network/VPC"


def test_load_aliases_tolerates_missing_files(tmp_path):
    assert load_aliases(str(tmp_path / "x.yaml"), str(tmp_path / "y.yaml")) == {}


ALIASES = {
    "storage": "Storage/_", "object storage": "Storage/Object Storage",
    "vpc": "Network/VPC", "lb": "Network/Load Balancer", "로드 밸런서": "Network/Load Balancer",
    "nat 게이트웨이": "Network/NAT Gateway",
}


def test_longest_alias_wins():
    assert detect_service("object storage에 파일 올리기", ALIASES) == "Storage/Object Storage"


def test_service_match_is_case_insensitive_and_korean():
    assert detect_service("Vpc 서브넷", ALIASES) == "Network/VPC"
    assert detect_service("로드 밸런서 생성", ALIASES) == "Network/Load Balancer"


def test_no_match_returns_fallback():
    assert detect_service("요금 문의", ALIASES) is None
    assert detect_service("그럼 삭제는?", ALIASES, fallback="Network/VPC") == "Network/VPC"
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest app/tests/test_intent.py -v` → `ModuleNotFoundError: No module named 'intent'`.

- [ ] **Step 3: 구현**

`app/intent.py`:
```python
"""질문 이해 — LLM 없이 규칙과 사전으로 의도와 서비스를 추정한다.

호출을 늘리면 요청 한도가 다시 문제가 되므로 여기서는 LLM 을 쓰지 않는다.
오판해도 검색 범위가 바뀌는 게 아니라 가중치만 달라지므로 비용이 낮다.
"""

import os

import yaml

APP_DIR = os.path.dirname(os.path.abspath(__file__))
GENERATED_ALIASES = os.path.join(APP_DIR, "services.generated.yaml")
MANUAL_ALIASES = os.path.join(APP_DIR, "services.yaml")

# 콘솔 절차를 묻는 신호. 하나라도 있으면 console.
CONSOLE_HINTS = (
    "어디서", "어떻게", "설정", "만들", "만드", "생성", "삭제", "메뉴", "버튼", "콘솔", "화면",
    "클릭", "추가", "등록", "연결", "변경", "절차", "방법", "하는 법", "하려면", "안 보여", "안보여",
)
# 절차 신호가 있어도 개념·API·요금 질문이면 general 로 되돌리는 신호.
GENERAL_OVERRIDES = ("차이", "api", "파라미터", "요금", "비용", "기준값", "유효기간", "릴리스", "지원 여부", "sla", "제한", "몇 개")


def detect_intent(question: str) -> str:
    q = question.lower()
    if any(h in q for h in GENERAL_OVERRIDES):
        return "general"
    return "console" if any(h in q for h in CONSOLE_HINTS) else "general"


def _read_yaml(path: str) -> dict:
    if not path or not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data if isinstance(data, dict) else {}


def load_aliases(generated_path: str | None = None, manual_path: str | None = None) -> dict[str, str]:
    """{별칭(소문자): '카테고리/서비스'}. 수동 사전이 자동 생성분을 덮어쓴다."""
    aliases: dict[str, str] = {}
    for path in (generated_path or GENERATED_ALIASES, manual_path or MANUAL_ALIASES):
        for service, names in _read_yaml(path).items():
            for name in names or []:
                key = " ".join(str(name).lower().split())
                if key:
                    aliases[key] = service
    return aliases


def detect_service(question: str, aliases: dict[str, str], fallback: str | None = None) -> str | None:
    q = " ".join(question.lower().split())
    hits = [alias for alias in aliases if alias in q]
    if not hits:
        return fallback
    return aliases[max(hits, key=len)]
```

`app/services.yaml` (수동 별칭 초안 — 시범 코퍼스 기준, 전체 적재 후 로그를 보며 늘린다):
```yaml
# 수동 별칭. services.generated.yaml 이 못 잡는 약칭·한글 표기. 검색 단계에서 둘을 합쳐 읽는다.
Network/VPC:
  - 브이피씨
  - 서브넷
  - 라우팅 테이블
Network/Load Balancer:
  - LB
  - 로드밸런서
  - 로드 밸런서
Network/Security Groups:
  - 보안 그룹
  - 보안그룹
  - 시큐리티 그룹
  - SG
Network/Floating IP:
  - 플로팅 IP
  - 플로팅IP
  - 유동 IP
Network/NAT Gateway:
  - NAT 게이트웨이
  - NAT
Network/Internet Gateway:
  - 인터넷 게이트웨이
Network/Peering Gateway:
  - 피어링 게이트웨이
  - 피어링
Network/VPN Gateway(Site-to-Site VPN):
  - VPN 게이트웨이
  - VPN
Network/Traffic Mirroring:
  - 트래픽 미러링
Network/DNS Plus:
  - DNS
Network/Network ACL:
  - 네트워크 ACL
  - ACL
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest app/tests/test_intent.py -v` → 27 passed (파라미터 20 + 7). 의도 판정 문장 중 틀리는 것이 있으면 `CONSOLE_HINTS`/`GENERAL_OVERRIDES` 를 조정한다 — 테스트 문장을 바꾸지 않는다.

- [ ] **Step 5: 커밋**

```bash
git add app/intent.py app/services.yaml app/tests/test_intent.py
git commit -m "feat(search): 규칙 기반 의도 판정과 별칭 사전 기반 서비스 추정

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: 하이브리드 검색 점수 보정과 `Candidate`

**Files:**
- Modify: `app/rag.py` (`hybrid_search` 재작성, `combine_scores` 신규, `Candidate` 신규, `build_bm25` 메타 확장)
- Modify: `app/ui.py` (검색 호출부)
- Test: `app/tests/test_combine_scores.py`

**Interfaces:**
- Consumes: Task 4 `tokenize`, Task 5 `detect_intent/detect_service/load_aliases`, Task 1 `vector_order_by`, `EMBED_DIM`
- Produces:
  - `@dataclass Candidate(content: str, source_path: str, service: str, doc_type: str, score: float)`
  - `combine_scores(vector_hits: list[tuple[Candidate, float]], bm25_hits: list[tuple[Candidate, float]], intent: str, service: str | None, keep: int = 12) -> list[Candidate]` — 순수 함수. `vector_hits`의 float 는 코사인 유사도(0~1), `bm25_hits`의 float 는 BM25 점수(최댓값으로 정규화). 기본 점수 = 두 정규화 값의 최댓값, 보정 곱: 둘 다 등장 ×1.2, `doc_type == "console" and intent == "console"` ×1.5, `service` 가 `Candidate.service` 의 `"카테고리/서비스"` 키와 같으면 ×1.3. 점수 내림차순 상위 `keep`
  - `hybrid_search(query: str, intent: str = "general", service: str | None = None, top_k: int = 20, keep: int = 12) -> list[Candidate]`
  - `service_key(candidate) -> str` — `f"{category}/{service}"` 를 만들기 위해 `doc_meta` 에 category 도 저장
  - `doc_meta[content] = (source_path, service, category, doc_type)` (4-튜플로 확장), `get_meta(content) -> (source_path, service)` 는 그대로 앞 두 개를 돌려준다(UI 호환)

- [ ] **Step 1: 실패하는 테스트**

`app/tests/test_combine_scores.py`:
```python
from rag import Candidate, combine_scores


def cand(name, doc_type="other", service="Network/VPC"):
    return Candidate(content=name, source_path=f"{service}/{name}.html", service=service, doc_type=doc_type, score=0.0)


def test_both_sources_and_console_boost_win():
    a = cand("a", doc_type="console")   # 벡터·BM25 둘 다, 콘솔
    b = cand("b")                        # 벡터만
    c = cand("c")                        # BM25만
    result = combine_scores([(a, 0.8), (b, 0.9)], [(a, 5.0), (c, 10.0)], intent="console", service=None)
    assert [r.content for r in result] == ["a", "c", "b"]
    assert abs(result[0].score - 0.8 * 1.2 * 1.5) < 1e-9        # max(0.8, 0.5)=0.8 ×1.2 ×1.5
    assert abs(result[1].score - 1.0) < 1e-9                    # 10/10
    assert abs(result[2].score - 0.9) < 1e-9


def test_console_boost_only_with_console_intent():
    a = cand("a", doc_type="console")
    b = cand("b")
    result = combine_scores([(a, 0.7), (b, 0.8)], [], intent="general", service=None)
    assert [r.content for r in result] == ["b", "a"]


def test_service_boost_uses_category_service_key():
    a = cand("a", service="Network/VPC")
    b = cand("b", service="Storage/Object Storage")
    result = combine_scores([(a, 0.7), (b, 0.8)], [], intent="general", service="Network/VPC")
    assert [r.content for r in result] == ["a", "b"]
    assert abs(result[0].score - 0.7 * 1.3) < 1e-9


def test_keep_limits_and_empty_inputs():
    hits = [(cand(str(i)), 1.0 - i * 0.01) for i in range(20)]
    assert len(combine_scores(hits, [], "general", None, keep=12)) == 12
    assert combine_scores([], [], "general", None) == []


def test_bm25_zero_scores_do_not_divide_by_zero():
    a = cand("a")
    result = combine_scores([], [(a, 0.0)], "general", None)
    assert result[0].score == 0.0
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest app/tests/test_combine_scores.py -v` → `ImportError: cannot import name 'Candidate' from 'rag'`.

- [ ] **Step 3: `rag.py` 구현**

상단 import 에 `from dataclasses import dataclass` 와 `from intent import detect_intent, detect_service, load_aliases` 를 추가하고 전역에 다음을 둔다:
```python
CANDIDATES = 20     # 벡터·BM25 각각 가져올 개수
RERANK_KEEP = 12    # 점수 보정 후 리랭킹에 넘길 개수
BOOST_BOTH = 1.2
BOOST_CONSOLE = 1.5
BOOST_SERVICE = 1.3

ALIASES: dict[str, str] = {}


@dataclass
class Candidate:
    content: str
    source_path: str
    service: str       # "카테고리/서비스"
    doc_type: str
    score: float
```
`build_bm25()` 를 다음으로 교체:
```python
def build_bm25():
    global bm25, bm25_corpus, EMBED_DIM, ALIASES

    conn = get_conn()
    EMBED_DIM = embedding_dim(conn) or 0
    cur = conn.cursor()

    cur.execute("SELECT content, source_path, service, category, doc_type FROM documents")
    rows = cur.fetchall()

    bm25_corpus = [r[0] for r in rows]
    for content, source, service, category, doc_type in rows:
        doc_meta[content] = (source, f"{category}/{service}", doc_type)

    bm25 = BM25Okapi([tokenize(doc) for doc in bm25_corpus])
    ALIASES = load_aliases()

    cur.close()
    conn.close()

    return len(bm25_corpus)


def get_meta(content):
    """청크 본문으로 (source_path, '카테고리/서비스') 를 되찾는다."""
    meta = doc_meta.get(content)
    return (meta[0], meta[1]) if meta else ("(출처 미상)", "unknown")


def _candidate(content) -> Candidate:
    source, service, doc_type = doc_meta.get(content, ("(출처 미상)", "unknown", "other"))
    return Candidate(content=content, source_path=source, service=service, doc_type=doc_type, score=0.0)
```
`combine_scores` 와 `hybrid_search` (기존 `hybrid_search` 교체):
```python
def combine_scores(vector_hits, bm25_hits, intent, service, keep=RERANK_KEEP):
    """벡터·BM25 결과를 하나의 점수로 합친다. 필터가 아니라 가중치만 준다."""
    max_bm25 = max((s for _, s in bm25_hits), default=0.0)
    vec = {c.content: (c, sim) for c, sim in vector_hits}
    kw = {c.content: (c, (s / max_bm25 if max_bm25 > 0 else 0.0)) for c, s in bm25_hits}

    merged: list[Candidate] = []
    for content in list(dict.fromkeys(list(vec) + list(kw))):
        cand = (vec.get(content) or kw.get(content))[0]
        base = max(vec.get(content, (None, 0.0))[1], kw.get(content, (None, 0.0))[1])
        score = base
        if content in vec and content in kw:
            score *= BOOST_BOTH
        if intent == "console" and cand.doc_type == "console":
            score *= BOOST_CONSOLE
        if service and cand.service == service:
            score *= BOOST_SERVICE
        merged.append(Candidate(cand.content, cand.source_path, cand.service, cand.doc_type, score))

    merged.sort(key=lambda c: c.score, reverse=True)
    return merged[:keep]


def hybrid_search(query, intent="general", service=None, top_k=CANDIDATES, keep=RERANK_KEEP):
    conn = get_conn()
    cur = conn.cursor()

    q_vec = to_pgvector(embed_query(query))
    cur.execute(f"""
    SELECT content, source_path, service, category, doc_type,
           1 - ({vector_order_by(EMBED_DIM)}) AS similarity
      FROM documents
     ORDER BY {vector_order_by(EMBED_DIM)}
     LIMIT %s;
    """, (q_vec, q_vec, top_k))

    vector_hits = []
    for content, source, svc, category, doc_type, sim in cur.fetchall():
        doc_meta.setdefault(content, (source, f"{category}/{svc}", doc_type))
        vector_hits.append((_candidate(content), float(sim)))

    cur.close()
    conn.close()

    scores = bm25.get_scores(tokenize(query))
    top_idx = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]
    bm25_hits = [(_candidate(bm25_corpus[i]), float(scores[i])) for i in top_idx if scores[i] > 0]

    return combine_scores(vector_hits, bm25_hits, intent, service, keep)
```
`search_docs(query, service=None)` 는 다음으로 교체 (Task 7 이 `rerank` 를 바꾸기 전까지 문자열 리스트를 유지):
```python
def search_docs(query, service=None):
    intent = detect_intent(query)
    svc = service or detect_service(query, ALIASES)
    candidates = hybrid_search(query, intent=intent, service=svc)
    return rerank(query, [c.content for c in candidates], top_k=TOP_K)
```

- [ ] **Step 4: `ui.py` 검색 호출부 수정**

`app/ui.py` 의 질문 처리 블록에서
```python
                search_q = rag.retrieval_query(question, history)
                status.update(label="1/3 하이브리드 검색 (벡터 + BM25)")
                docs = rag.hybrid_search(search_q, top_k=candidates)

                status.update(label=f"2/3 관련도 평가 ({len(docs)}건)")
                docs = rag.rerank(search_q, docs, top_k=top_k)
```
→
```python
                search_q = rag.retrieval_query(question, history)
                intent = rag.detect_intent(question)
                # 후속 질문("그럼 삭제는?")은 직전 턴의 서비스를 이어받는다 (스펙 4-1).
                service = rag.detect_service(search_q, rag.ALIASES, fallback=st.session_state.get("last_service"))
                st.session_state.last_service = service
                status.update(label=f"1/3 하이브리드 검색 (벡터 + BM25) · {intent} · {service or '서비스 미상'}")
                candidates_found = rag.hybrid_search(search_q, intent=intent, service=service, top_k=candidates)
                docs = [c.content for c in candidates_found]

                status.update(label=f"2/3 관련도 평가 ({len(docs)}건)")
                docs = rag.rerank(search_q, docs, top_k=top_k)
```

- [ ] **Step 5: 통과 확인과 UI 헤드리스 확인**

Run: `python -m pytest -q` → 전체 통과 (`test_combine_scores` 5개 포함).
Run (`app/`에서, DB_HOST·키·`PYTHONIOENCODING` 설정) 다음 스크립트를 스크래치 파일로 저장해 실행:
```python
import os, sys; APP = os.getcwd(); sys.path.insert(0, APP)
from streamlit.testing.v1 import AppTest
at = AppTest.from_file(os.path.join(APP, "ui.py"), default_timeout=300); at.run()
at.chat_input[0].set_value("VPC에 서브넷을 만드는 방법을 알려줘").run()
print("exceptions:", [e.message for e in at.exception] or "none")
print("status labels:", [s.label for s in at.status])
print("roles:", [m.name for m in at.chat_message])
```
Expected: 예외 없음, 상태 라벨에 `console · Network/VPC` 포함, roles `['user', 'assistant']`.

- [ ] **Step 6: 커밋**

```bash
git add app/rag.py app/ui.py app/tests/test_combine_scores.py
git commit -m "feat(search): 의도·서비스 기반 점수 보정과 Candidate 로 하이브리드 검색 재구성

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: 리랭킹 — 추론 끔, 근거 판정, 12건×900자

**Files:**
- Modify: `app/llm.py` (`chat`에 `think` 인자)
- Modify: `app/rag.py` (`rerank`, `parse_rerank`, `search_docs`)
- Modify: `app/ui.py` (리랭킹 결과 튜플 처리)
- Test: `app/tests/test_rerank_parse.py`

**Interfaces:**
- Produces:
  - `llm.chat(prompt, system=..., temperature=0.5, max_tokens=1024, think=True) -> str` — `think=False` 면 `extra_body={"chat_template_kwargs": {"enable_thinking": False}}` 를 붙인다
  - `rag.parse_rerank(text: str, n: int) -> tuple[list[float], list[bool]] | None` — 응답에서 `점수` 배열과 `근거` 배열(1/0)을 찾아 둘 다 길이 n 이면 반환
  - `rag.rerank(query: str, docs: list[str], top_k: int = 5) -> tuple[list[str], bool | None]` — (상위 문서, grounded). grounded 는 상위 문서 중 근거=1 이 하나라도 있으면 True, 없으면 False, 파싱 실패면 None
  - `rag.search_docs(query, service=None) -> tuple[list[str], bool | None]`
  - `rag.RERANK_DOC_CHARS = 900`

- [ ] **Step 1: 실패하는 테스트**

`app/tests/test_rerank_parse.py`:
```python
from rag import parse_rerank


def test_parses_scores_and_grounded_arrays():
    text = "점수: [10, 6, 0]\n근거: [1, 1, 0]"
    assert parse_rerank(text, 3) == ([10.0, 6.0, 0.0], [True, True, False])


def test_accepts_json_object_form():
    text = '{"점수": [8, 2], "근거": [1, 0]}'
    assert parse_rerank(text, 2) == ([8.0, 2.0], [True, False])


def test_wrong_length_returns_none():
    assert parse_rerank("점수: [1, 2]\n근거: [1]", 2) is None
    assert parse_rerank("점수: [1, 2, 3]\n근거: [1, 0, 1]", 2) is None


def test_missing_grounded_array_returns_none():
    assert parse_rerank("[10, 6, 0]", 3) is None
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest app/tests/test_rerank_parse.py -v` → `ImportError: cannot import name 'parse_rerank'`.

- [ ] **Step 3: `llm.py` — `think` 인자**

`chat()` 시그니처를 `def chat(prompt, system="You are a helpful assistant.", temperature=0.5, max_tokens=1024, think=True):` 로 바꾸고, `_retry(client.chat.completions.create, ...)` 호출에 다음 인자를 추가한다:
```python
        extra_body=None if think else {"chat_template_kwargs": {"enable_thinking": False}},
```
`chat()` 의 독스트링(없으면 추가): `"""think=False 면 Nemotron 의 추론 토큰을 끈다. 리랭킹처럼 짧은 구조화 출력은 추론 없이도 정확하고 30배 빠르다(실측 34초→1.3초)."""`

- [ ] **Step 4: `rag.py` — 리랭킹 교체**

`RERANK_DOC_CHARS = 700` → `RERANK_DOC_CHARS = 900`. `parse_scores` 와 `rerank` 를 다음으로 교체:
```python
_ARRAY = re.compile(r"\[[\d\s.,]*\]")


def _numbers(array_text: str) -> list[float]:
    return [float(v) for v in re.findall(r"\d+(?:\.\d+)?", array_text)]


def parse_rerank(text: str, n: int):
    """응답의 마지막 두 숫자 배열을 (점수, 근거) 로 읽는다. 둘 다 길이 n 일 때만 돌려준다.

    순서는 프롬프트가 고정한다: 점수 줄이 먼저, 근거 줄이 나중.
    """
    arrays = _ARRAY.findall(text)
    if len(arrays) < 2:
        return None

    scores = _numbers(arrays[-2])
    grounded_raw = _numbers(arrays[-1])
    if len(scores) != n or len(grounded_raw) != n:
        return None
    return scores, [v >= 1 for v in grounded_raw]


def rerank(query, docs, top_k=TOP_K):
    """후보 전체를 추론 끈 한 번의 호출로 채점하고, 답이 있는 문서인지도 함께 받는다.

    반환: (상위 문서, grounded). grounded 는 상위 문서 중 '근거 있음' 이 하나라도 있으면 True,
    하나도 없으면 False, 응답을 못 읽었으면 None (검색 순서를 그대로 쓴다).
    """
    if not docs:
        return [], False

    listing = "\n\n".join(f"[{i}] {d[:RERANK_DOC_CHARS]}" for i, d in enumerate(docs))
    prompt = f"""질문과 각 문서의 관련도를 0~10 점으로 평가하고, 그 문서만으로 질문에 답할 수 있는지(1/0)도 표시해.

질문:
{query}

문서 목록 ({len(docs)}건):
{listing}

아래 두 줄만 출력해. 설명은 쓰지 마.
점수: [점수0, 점수1, ..., 점수{len(docs) - 1}]
근거: [답가능0, 답가능1, ..., 답가능{len(docs) - 1}]
"""

    try:
        parsed = parse_rerank(chat(prompt, temperature=0.0, max_tokens=512, think=False), len(docs))
    except Exception as e:
        print(f"  [리랭킹 실패] {type(e).__name__}: {e} → 검색 순서 사용")
        parsed = None

    if parsed is None:
        return docs[:top_k], None

    scores, grounded = parsed
    order = sorted(range(len(docs)), key=lambda i: scores[i], reverse=True)[:top_k]
    return [docs[i] for i in order], any(grounded[i] for i in order)
```
`search_docs` 를 다음으로:
```python
def search_docs(query, service=None):
    intent = detect_intent(query)
    svc = service or detect_service(query, ALIASES)
    candidates = hybrid_search(query, intent=intent, service=svc)
    return rerank(query, [c.content for c in candidates], top_k=TOP_K)
```
`ask()` 안의 `docs = search_docs(...)` → `docs, _ = search_docs(...)`. `langchain_search()` 안의 `docs = search_docs(query)` → `docs, _ = search_docs(query)`.

- [ ] **Step 5: `ui.py` — 튜플 처리와 근거 없음 표시**

`docs = rag.rerank(search_q, docs, top_k=top_k)` → `docs, grounded = rag.rerank(search_q, docs, top_k=top_k)`.
`answer = st.write_stream(rag.answer_stream(question, docs, history))` 바로 앞에:
```python
            if grounded is False:
                st.caption("관련도 평가 결과 근거가 될 문서를 찾지 못했습니다. 답변은 참고만 하세요.")
            elif grounded is None:
                st.caption("관련도 확인 실패 — 검색 순서를 그대로 사용했습니다.")
```
(근거 없을 때 답변을 아예 생략하는 처리는 2단계-B 의 답변 형식 작업에서 한다.)

- [ ] **Step 6: 통과·속도 확인**

Run: `python -m pytest -q` → 전체 통과.
Run (`app/`, 환경 설정) — 스크래치 스크립트:
```python
import os, sys, time; sys.path.insert(0, os.getcwd())
import rag; rag.build_bm25()
for q in ["VPC에 서브넷을 추가하는 방법을 알려줘", "NAT 게이트웨이는 어떻게 만들어?", "오늘 서울 날씨"]:
    t0 = time.time(); intent = rag.detect_intent(q); svc = rag.detect_service(q, rag.ALIASES)
    cands = rag.hybrid_search(q, intent=intent, service=svc); t1 = time.time()
    docs, grounded = rag.rerank(q, [c.content for c in cands]); t2 = time.time()
    print(f"{q[:20]:20} intent={intent} svc={svc} 검색 {t1-t0:4.1f}s 리랭킹 {t2-t1:4.1f}s grounded={grounded} top={[c.doc_type for c in cands[:3]]}")
```
Expected: 리랭킹 5초 이내(실측 1~2초), 첫 두 질문 `grounded=True`, 날씨 `grounded=False`, 첫 질문 상위 후보에 `console` 포함.

- [ ] **Step 7: 커밋**

```bash
git add app/llm.py app/rag.py app/ui.py app/tests/test_rerank_parse.py
git commit -m "feat(search): 추론 끈 리랭킹으로 34초→1초대, 근거 판정 추가

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: 전체 재수집·재적재·별칭 재생성·지연 측정

**Files:**
- Create: `eval/bench_latency.py`
- Modify: `README.md`, `app/services.generated.yaml`

**Interfaces:**
- Consumes: 모든 이전 태스크
- Produces: `nhn_cloud_docs/` = 26개 카테고리 전체(새 구조), `documents` = 전체 코퍼스, `eval/bench_latency.py` 로 동시 1/3/6 측정 결과를 README 에 기록

- [ ] **Step 1: 구 코퍼스 이동, 전체 수집 (1~1.5시간, 백그라운드)**

```bash
mv nhn_cloud_docs nhn_cloud_docs_old      # 구 형식 431개 파일. 삭제하지 않고 보관(.gitignore 의 nhn_cloud_docs_*/ 에 포함)
PYTHONIOENCODING=utf-8 python crawlling/crawl.py --save-dir nhn_cloud_docs > crawl_full.log 2>&1 &
```
진행은 `tail -3 crawl_full.log` 와 `python -c "import json;m=json.load(open('nhn_cloud_docs/manifest.json',encoding='utf-8'));import collections;print(len(m),collections.Counter(e['status'] for e in m.values()))"` 로 확인. 끝나면 `=== 결과 ===` 블록을 기록. `error` 가 있으면 같은 명령을 한 번 더 실행(ok 는 건너뜀). `crawl_full.log` 는 커밋하지 않는다(루트 `.gitignore` 에 `*.log` 추가).

- [ ] **Step 2: 수집 결과 검증**

```bash
find nhn_cloud_docs -name "*.html" | wc -l
find nhn_cloud_docs -name "*.html" | cut -d/ -f2 | sort -u | wc -l        # 카테고리 수 (26 기대)
find nhn_cloud_docs -name "콘솔 사용 가이드.html" | wc -l                    # 1단계 이전 36 → 크게 증가 기대
find nhn_cloud_docs -path "*/images/*" -type f | wc -l
```
Expected: 문서 1,000개 이상, 카테고리 26, 콘솔 가이드 100개 안팎, 이미지 수천 장. `no_breadcrumb` 문서 목록은 README 에 수와 예시 3개를 기록.

- [ ] **Step 3: 전체 재적재와 별칭 재생성**

Run (`app/`, PowerShell, DB_HOST·키·`PYTHONIOENCODING`, `DOCS_DIR` 은 기본값):
```powershell
python ingest.py --rebuild 2>&1 | Tee-Object -FilePath ..\ingest_full.log | Select-Object -Last 5
python aliases.py
```
Expected: `완료: 문서 N개 적재, 0개 건너뜀, K개 실패, 0개 정리 (청크 M개)`. 실패 문서가 있으면 로그의 원인을 README 에 요약하고, 재시도 가능한 것(429/503)은 `python ingest.py` 재실행으로 마저 적재. `services.generated.yaml` 은 100개 안팎의 서비스로 갱신되어 커밋한다.
Run: `docker exec pgvector psql -U devops -d ragdb -tAc "SELECT count(*), count(DISTINCT source_path), count(DISTINCT service) FROM documents; SELECT doc_type, count(*) FROM documents GROUP BY 1 ORDER BY 2 DESC;"` 결과를 기록.

- [ ] **Step 4: 지연 측정 스크립트를 저장소에 추가**

`eval/bench_latency.py`:
```python
"""동시 질문 1/3/6 개를 실제 파이프라인에 넣어 단계별 지연과 재시도 횟수를 잰다.

    cd app && DB_HOST=localhost python ../eval/bench_latency.py
"""
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))

import llm
import rag

QUESTIONS = [
    "VPC에 서브넷을 추가하는 방법을 알려줘",
    "로드 밸런서를 생성하는 절차는?",
    "플로팅 IP를 인스턴스에 연결하려면 어떻게 해?",
    "NAT 게이트웨이는 어떻게 만들어?",
    "시큐리티 그룹에 규칙을 추가하는 방법",
    "DNS Plus에서 도메인을 등록하는 방법",
    "전자세금계산서는 콘솔 어디서 확인해?",
    "VPN 게이트웨이 설정 방법 알려줘",
    "피어링 게이트웨이는 어떻게 생성해?",
    "트래픽 미러링은 어떻게 설정해?",
]

_lock = threading.Lock()
retries = {"n": 0}


def _count_retries(*args, **kwargs):
    if any("재시도" in str(a) for a in args):
        with _lock:
            retries["n"] += 1


llm.print = _count_retries
rag.print = _count_retries


def run_one(q):
    t0 = time.time()
    try:
        intent = rag.detect_intent(q)
        service = rag.detect_service(q, rag.ALIASES)
        cands = rag.hybrid_search(q, intent=intent, service=service)
        t1 = time.time()
        docs, grounded = rag.rerank(q, [c.content for c in cands])
        t2 = time.time()
        answer = llm.chat(rag.build_prompt(q, docs), system=rag.SYSTEM_PROMPT, max_tokens=2048)
        t3 = time.time()
        return dict(q=q, ok=True, search=t1 - t0, rerank=t2 - t1, answer=t3 - t2, total=t3 - t0,
                    grounded=grounded, chars=len(answer))
    except Exception as e:
        return dict(q=q, ok=False, total=time.time() - t0, err=f"{type(e).__name__}: {str(e)[:80]}")


def main():
    print("BM25 구축:", rag.build_bm25(), "chunks")
    summary = []
    for n, qs in ((1, QUESTIONS[0:1]), (3, QUESTIONS[1:4]), (6, QUESTIONS[4:10])):
        retries["n"] = 0
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=n) as pool:
            results = list(pool.map(run_one, qs))
        wall = time.time() - t0
        oks = [r for r in results if r["ok"]]
        print(f"\n=== 동시 {n}개 === 벽시계 {wall:.1f}초, 성공 {len(oks)}/{n}, 재시도 {retries['n']}회")
        for r in results:
            if r["ok"]:
                print(f"  {r['total']:5.1f}초 (검색 {r['search']:4.1f} / 리랭킹 {r['rerank']:5.1f} / 답변 {r['answer']:5.1f}) "
                      f"grounded={r['grounded']} {r['chars']:4d}자  {r['q'][:22]}")
            else:
                print(f"  실패 {r['total']:5.1f}초  {r['err']}  {r['q'][:22]}")
        totals = [r["total"] for r in results]
        summary.append((n, wall, len(oks), retries["n"], max(totals), sum(r["total"] for r in oks) / max(len(oks), 1)))
        time.sleep(10)

    print("\n=== 요약 ===\n동시 | 벽시계 | 성공 | 재시도 | 최대 | 평균")
    for n, wall, ok, rt, mx, avg in summary:
        print(f"{n:>4} | {wall:6.1f}초 | {ok}/{n} | {rt:>4}회 | {mx:5.1f}초 | {avg:5.1f}초")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: 측정 실행과 README 갱신**

Run (`app/`, 환경 설정): `python ../eval/bench_latency.py`
기준(1단계 측정): 동시 1개 34.7초(리랭킹 19.5), 동시 6개 평균 59.4초. 기대: 리랭킹 1~3초, 총 시간이 절반 이하.

`README.md` 에 절을 추가한다: "## 코퍼스 현황" (수집 문서 수·카테고리·콘솔 가이드 수·이미지 수·청크 수·`no_breadcrumb` 수, 측정일), "## 검색 동작" (의도·서비스 추정, 부스트 값, 리랭킹 12×900·추론 끔·근거 판정, `services.yaml` 로 별칭 추가하는 법), "## 지연 측정" (`eval/bench_latency.py` 사용법과 이번 결과 표). 실행 순서 절에 `python ingest.py` 가 전체 실행에서 사라진 문서를 정리한다는 점과 `--allow-no-manifest` 를 반영.

- [ ] **Step 6: 커밋**

`.gitignore` 에 `*.log` 추가.
```bash
git add .gitignore eval/bench_latency.py README.md app/services.generated.yaml
git commit -m "feat: 26개 카테고리 전체 재수집·재적재, 별칭 사전 재생성, 지연 측정 스크립트

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## 완료 기준 (2단계-A)

- 단위 테스트 전체 통과(신규: chunker 8, tokenize 5, intent 27, combine 5, rerank parse 4), 통합 테스트 4개 통과 — 모두 `ragdb_test` 사용
- `documents_embedding_hnsw` 가 halfvec 표현식으로 존재하고 EXPLAIN 에 Index Scan
- `nhn_cloud_docs/` 에 26개 카테고리 전체가 새 구조로 있고 DB 에 전체 코퍼스 적재
- `eval/bench_latency.py` 결과에서 리랭킹 5초 이내, 재시도 0~소수
- 기존 UI 가 새 검색 위에서 동작 (AppTest 확인)

2단계-B(답변 형식·스크린샷 UI·피드백·로그·Dockerfile·refresh.sh·평가 30문항)는 이 계획이 끝난 뒤 작성한다.
