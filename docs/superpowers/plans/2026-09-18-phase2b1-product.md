# 2단계-B-1 "제품" 구현 계획 — 콘솔형 답변·스크린샷·피드백·질문 로그·관리자 페이지

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 2단계-A의 검색 위에 스펙 3·4절을 구현한다 — 콘솔 의도 답변은 메뉴 경로 + 번호 단계 + 인라인 스크린샷으로 나오고, 모든 질문이 `questions`에 기록되며, 👍/👎 피드백과 앱 내 관리자 페이지가 생긴다.

**Architecture:** `rag.build_prompt`가 `Candidate` 목록을 받아 프롬프트와 그림 순번표(`image_map`)를 함께 돌려주고, 순수 모듈 `answer_render`가 `{{img:N}}` 마커를 분할한다. `qlog`가 `questions` INSERT/UPDATE를, `admin_stats`가 집계 SQL을 맡는다. `ui.py`는 `st.navigation` 셸이 되고 실제 화면은 `chat_page.py`·`admin_page.py`로 나뉜다. DB 컬럼 추가는 `db.migrate`(멱등 `ADD COLUMN IF NOT EXISTS`)로, 재적재 없이 UI 기동 시 적용된다.

**Tech Stack:** Python 3.12, Streamlit 1.64 (`st.navigation`, `st.write_stream`, AppTest), psycopg2, pytest (단위: `python -m pytest` 저장소 루트에서; 통합: `-m integration`, `ragdb_test`).

**Spec:** `docs/superpowers/specs/2026-09-18-console-guide-bot-production-design.md` 3절·4절·6절·7절 (기본 스펙 `2026-09-17-console-guide-bot-design.md` 5절 참조).

## Global Constraints

- 브랜치 `feature/phase2b` (2A 브랜치 `feature/phase2a-search` 위). 커밋 메시지 끝에 `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- 테스트 실행은 저장소 루트에서 `python -m pytest` (pytest.ini: `testpaths = app/tests crawlling/tests`, 기본 `-m "not integration"`). 통합 테스트는 `DB_HOST=localhost python -m pytest -m integration app/tests/<파일>` — `ragdb_test` DB만 쓴다. **실데이터 DB `ragdb`에 `--rebuild`나 DELETE를 하지 않는다.**
- 앱 코드는 `app/` 안에서 서로를 최상위 모듈로 import 한다 (`import rag`, `from db import get_conn`). 패키지 상대 import 를 쓰지 않는다.
- 그림 순번 N은 후보 순서대로 1부터 연속, `missing=True` 이미지는 순번 없음·프롬프트 미포함 (스펙 3-1). 캡션은 앞 60자.
- 마커 정규식 `\{\{img:(\d+)\}\}`. 범위 밖 번호는 제거하고 stderr에 남긴다 (스펙 3-4).
- `grounded is False`면 LLM을 호출하지 않고 고정 문구 `제공된 문서에서 확인되지 않습니다.` + 추정 서비스, 출처 미표시 (스펙 3-3).
- `questions` 추가 컬럼: `session_id TEXT`, `answer TEXT`, `retrieval_query TEXT`. `documents` 추가 컬럼: `ingested_at TIMESTAMPTZ DEFAULT now()`. 모두 `ADD COLUMN IF NOT EXISTS` (스펙 4-2). 사용자 식별 정보는 저장하지 않는다.
- 로그 INSERT/UPDATE 실패는 화면에 영향 없이 stderr (스펙 6절).
- 예시 질문 4개: `VPC에 서브넷을 추가하는 방법`, `로드 밸런서를 생성하는 절차`, `플로팅 IP를 인스턴스에 연결하는 방법`, `Object Storage에 컨테이너를 만드는 방법` (스펙 4-1).
- 관리자 페이지 기간 선택: `7일 / 30일 / 전체`. 목록은 각 최근 20건. 느린 질문 기준 30초 (스펙 4-3).
- 파일 인코딩 UTF-8, 한국어 주석·문구는 기존 코드 톤을 따른다.

---

## 파일 구조

| 파일 | 책임 |
|---|---|
| `app/rag.py` (수정) | `ImageRef`, `number_images`, `build_prompt(question, cands, history, intent) -> (prompt, image_map)`, 의도별 시스템 프롬프트, `answer_stream(...) -> (stream, image_map)`. 문자열 호환 경로(`rerank`, `_candidate`, `_as_candidate`, `get_meta`, `doc_meta`) 제거 |
| `app/answer_render.py` (신규) | 순수 함수: `split_markers`, `valid_markers`, `NOT_GROUNDED_MESSAGE` |
| `app/db.py` (수정) | `migrate(conn)` — 컬럼 추가 멱등. `init_schema` 끝에서 호출 |
| `app/qlog.py` (신규) | `sources_of`, `log_question`, `set_feedback` |
| `app/admin_stats.py` (신규) | `since_for`, `summary`, `by_service`, `recent_down`, `recent_ungrounded`, `recent_slow`, `index_status` |
| `app/chat_page.py` (신규) | 챗 화면 전체 (기존 `ui.py` 본문 이동 + 스펙 4-1) |
| `app/admin_page.py` (신규) | 관리자 화면 |
| `app/ui.py` (축소) | `set_page_config` + CSS + `st.navigation` |
| `app/styles.py` (수정) | `.nhn-answer-tag`, `.nhn-source-row`, `.nhn-section` |
| `eval/bench_latency.py` (수정) | 새 `build_prompt`/`rerank_candidates` 시그니처 |
| `app/tests/conftest.py` (신규) | `test_db` 픽스처 (test_ingest_db.py에서 이동) |
| `app/tests/test_search_units.py` (수정), `test_answer_render.py`, `test_qlog_db.py`, `test_admin_stats_db.py`, `test_ui_apptest.py` (신규) | 테스트 |

---

### Task 1: `build_prompt`가 Candidate와 그림 순번표를 다루고, 의도별 시스템 프롬프트를 고른다

**Files:**
- Modify: `app/rag.py`
- Modify: `app/tests/test_search_units.py`
- Modify: `eval/bench_latency.py:50-52`

**Interfaces:**
- Consumes: `rag.Candidate` (2A) — `content, source_path, service, doc_type, score, section_path, source_url, images: list[dict(path, caption, alt, missing)]`.
- Produces:
  - `@dataclass(frozen=True) class ImageRef: path: str; caption: str`
  - `CAPTION_CHARS = 60`
  - `number_images(cands: list[Candidate]) -> tuple[dict[int, ImageRef], list[list[int]]]` — (image_map, 후보별 순번 목록)
  - `build_prompt(question, cands: list[Candidate], history=None, intent="general") -> tuple[str, dict[int, ImageRef]]`
  - `SYSTEM_PROMPT` (general, 기존), `CONSOLE_SYSTEM_PROMPT`, `system_prompt(intent) -> str`
  - `answer_stream(question, cands, history=None, intent="general") -> tuple[Iterator[str], dict[int, ImageRef]]`
  - `ask(question, history=None) -> str` (유지, 내부만 수정)
  - 제거: `rerank`, `_candidate`, `_as_candidate`, `get_meta`, `doc_meta`

- [ ] **Step 1: 실패하는 테스트 작성**

`app/tests/test_search_units.py`에서 문자열 호환 테스트 3개(`test_rerank_wrapper_returns_strings_and_grounded`, `test_rerank_wrapper_handles_unknown_content`, `test_build_prompt_accepts_strings_via_doc_meta`)와 `_candidate`를 쓰는 중복 청크 테스트(파일 끝, `rag._candidate(dup)` 사용)를 **삭제**하고, 기존 `build_prompt` 테스트를 튜플 반환에 맞게 고친 뒤 아래를 추가한다.

```python
# 기존 두 테스트는 prompt, _ = rag.build_prompt(...) 로 바꾼다.
def test_build_prompt_header_names_doc_and_section():
    prompt, _ = rag.build_prompt("VPC 서브넷 만드는 법", [cand("콘솔 사용 가이드")])
    assert (
        "[문서 1] 서비스: Network/VPC · 문서: 콘솔 사용 가이드 · "
        "섹션: 서브넷 생성 · 출처: https://docs.nhncloud.com/ko/콘솔 사용 가이드/"
    ) in prompt
    assert "콘솔 사용 가이드 본문" in prompt
    assert "VPC 서브넷 만드는 법" in prompt


def test_build_prompt_numbers_documents_from_one():
    prompt, _ = rag.build_prompt("q", [cand("a"), cand("b")])
    assert "[문서 1]" in prompt and "[문서 2]" in prompt


def test_build_prompt_includes_history():
    history = [{"role": "user", "content": "VPC 가 뭐야"}, {"role": "assistant", "content": "가상 네트워크다"}]
    prompt, _ = rag.build_prompt("그럼 서브넷은?", [cand("a")], history)
    assert "이전 대화:" in prompt
    assert "사용자: VPC 가 뭐야" in prompt


def test_build_prompt_falls_back_to_source_path_without_url():
    c = cand("a")
    c.source_url = None
    prompt, _ = rag.build_prompt("q", [c])
    assert "출처: Network/VPC/a.html" in prompt


# ---------------------------------------------------------------- 그림 순번

def with_images(name, images):
    c = cand(name)
    c.images = images
    return c


def test_number_images_is_sequential_across_candidates_and_skips_missing():
    a = with_images("a", [
        {"path": "p/a1.png", "caption": "첫 화면", "alt": "", "missing": False},
        {"path": "p/a2.png", "caption": "없는 그림", "alt": "", "missing": True},
    ])
    b = with_images("b", [{"path": "p/b1.png", "caption": "두 번째 문서 화면", "alt": "", "missing": False}])

    image_map, per_cand = rag.number_images([a, b])

    assert list(image_map) == [1, 2]
    assert image_map[1] == rag.ImageRef(path="p/a1.png", caption="첫 화면")
    assert image_map[2].path == "p/b1.png"
    assert per_cand == [[1], [2]]


def test_number_images_truncates_caption():
    long = "가" * 100
    a = with_images("a", [{"path": "p/a.png", "caption": long, "alt": "", "missing": False}])
    image_map, _ = rag.number_images([a])
    assert image_map[1].caption == "가" * rag.CAPTION_CHARS


def test_number_images_empty_when_no_images():
    c = cand("a")
    c.images = []
    assert rag.number_images([c]) == ({}, [[]])


def test_build_prompt_lists_images_under_their_document_and_returns_map():
    a = with_images("a", [{"path": "p/a1.png", "caption": "첫 화면", "alt": "", "missing": False}])
    b = with_images("b", [
        {"path": "p/b0.png", "caption": "빠진 그림", "alt": "", "missing": True},
        {"path": "p/b1.png", "caption": "두 번째", "alt": "", "missing": False},
    ])

    prompt, image_map = rag.build_prompt("q", [a, b])

    assert "[그림 1] 첫 화면" in prompt
    assert "[그림 2] 두 번째" in prompt
    assert "빠진 그림" not in prompt
    # 그림 줄은 자기 문서 블록 안(다음 문서 머리말 앞)에 있어야 한다.
    assert prompt.index("[그림 1]") < prompt.index("[문서 2]")
    assert image_map == {1: rag.ImageRef("p/a1.png", "첫 화면"), 2: rag.ImageRef("p/b1.png", "두 번째")}


# ---------------------------------------------------------------- 의도별 시스템 프롬프트

def test_system_prompt_by_intent():
    assert rag.system_prompt("console") is rag.CONSOLE_SYSTEM_PROMPT
    assert rag.system_prompt("general") is rag.SYSTEM_PROMPT
    assert rag.system_prompt("뭔가 이상한 값") is rag.SYSTEM_PROMPT


def test_console_prompt_spells_out_format_rules():
    p = rag.CONSOLE_SYSTEM_PROMPT
    assert "메뉴 경로: 문서에 명시되지 않음" in p
    assert "{{img:N}}" in p
    assert "주의" in p
    # 공통 근거 제한 문구는 두 프롬프트에 모두 있어야 한다.
    assert "제공된 문서에서 확인되지 않습니다" in p
    assert "제공된 문서에서 확인되지 않습니다" in rag.SYSTEM_PROMPT


def test_answer_stream_returns_stream_and_map(monkeypatch):
    seen = {}

    def fake_stream(prompt, system=None, **kw):
        seen["system"] = system
        seen["prompt"] = prompt
        yield "답"

    monkeypatch.setattr(rag, "chat_stream", fake_stream)
    a = with_images("a", [{"path": "p/a1.png", "caption": "c", "alt": "", "missing": False}])

    stream, image_map = rag.answer_stream("q", [a], intent="console")

    assert "".join(stream) == "답"
    assert seen["system"] is rag.CONSOLE_SYSTEM_PROMPT
    assert "[그림 1] c" in seen["prompt"]
    assert image_map == {1: rag.ImageRef("p/a1.png", "c")}


def test_string_compat_paths_are_gone():
    for name in ("rerank", "_candidate", "_as_candidate", "get_meta", "doc_meta"):
        assert not hasattr(rag, name), name
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest app/tests/test_search_units.py -q`
Expected: FAIL — `AttributeError: module 'rag' has no attribute 'number_images'`, `ImageRef` 없음, `build_prompt`가 문자열 반환.

- [ ] **Step 3: 구현**

`app/rag.py`:

1. 파일 상단 `doc_meta = {}` 정의와 주석 삭제. `build_bm25`에서 `doc_meta.clear()`와 `doc_meta.setdefault(...)` 삭제. `hybrid_search`에서 `doc_meta.setdefault(...)` 삭제. `get_meta`, `_candidate`, `rerank`, `_as_candidate` 함수 삭제.

2. `Candidate` 정의 아래에 추가:

```python
# 답변에 인라인으로 붙일 스크린샷 한 장. path 는 DOCS_DIR 기준 상대 경로.
@dataclass(frozen=True)
class ImageRef:
    path: str
    caption: str


CAPTION_CHARS = 60


def number_images(cands: list[Candidate]) -> tuple[dict[int, ImageRef], list[list[int]]]:
    """후보 순서대로 missing 아닌 이미지에 1부터 순번을 매긴다.

    반환: (순번 → ImageRef, 후보별 순번 목록). 프롬프트의 '[그림 N]' 과 답변의 '{{img:N}}' 이
    같은 N 을 쓰도록, 순번표는 프롬프트와 함께 세션에 저장한다 (스펙 3-1).
    """
    image_map: dict[int, ImageRef] = {}
    per_cand: list[list[int]] = []
    for c in cands:
        nums: list[int] = []
        for img in c.images or []:
            if img.get("missing"):
                continue
            n = len(image_map) + 1
            image_map[n] = ImageRef(path=img["path"], caption=(img.get("caption") or "")[:CAPTION_CHARS])
            nums.append(n)
        per_cand.append(nums)
    return image_map, per_cand
```

3. 시스템 프롬프트를 공통부 + 의도별로 나눈다 (기존 `SYSTEM_PROMPT` 정의를 아래로 교체):

```python
_SYSTEM_COMMON = (
    "너는 NHN Cloud 공식 문서를 근거로 답하는 기술 지원 어시스턴트다. "
    "반드시 제공된 문서 내용만 근거로 삼고, 문서에 없는 내용은 지어내지 말고 "
    "'제공된 문서에서 확인되지 않습니다'라고 밝혀라. "
    "이전 대화가 주어지면 '그것', '거기' 같은 지시어가 무엇을 가리키는지 그 맥락으로 해석해 이어서 답해라. "
    "단, 이전 대화 내용 자체를 근거로 삼지 말고 근거는 언제나 제공된 문서에서만 찾아라. "
    "각 문서 본문의 첫 줄 '문서명 > 섹션 경로'는 문서 안 위치이지 콘솔 메뉴 경로가 아니다. "
    "콘솔 메뉴 경로는 본문에 명시된 것만 써라. 답변은 한국어로 해라. "
)

SYSTEM_PROMPT = _SYSTEM_COMMON + "절차는 번호 목록으로, 파라미터·필드는 표로 정리해라."

# 콘솔 절차 질문의 답변 형식 (스펙 3-2). 그림 번호는 프롬프트의 '[그림 N]' 과 같은 N 이다.
CONSOLE_SYSTEM_PROMPT = _SYSTEM_COMMON + (
    "답변 형식: "
    "첫 줄에는 문서 본문에 명시된 콘솔 메뉴 경로만 '콘솔 > Network > VPC > Subnet' 형태로 써라. "
    "문서에 메뉴 경로가 없으면 첫 줄에 '메뉴 경로: 문서에 명시되지 않음'이라고 써라. "
    "그다음 절차를 번호 목록으로 써라. 문서 블록에 '[그림 N]'으로 표시된 스크린샷이 어느 단계에 해당하면 "
    "그 단계 문장 끝에 {{img:N}} 를 붙여라 (예: '3. 서브넷 생성을 클릭합니다. {{img:2}}'). "
    "문서 블록에 없는 그림 번호는 절대 쓰지 마라. "
    "문서에 '주의' 또는 '참고' 내용이 있을 때만 마지막에 '주의' 항목을 쓰고, 없으면 쓰지 마라."
)


def system_prompt(intent: str) -> str:
    return CONSOLE_SYSTEM_PROMPT if intent == "console" else SYSTEM_PROMPT
```

4. `build_prompt`·`ask`·`answer_stream` 교체:

```python
def build_prompt(question, cands: list[Candidate], history=None, intent="general"):
    """(프롬프트, 그림 순번표). 블록 머리말에 서비스·문서명·섹션·출처를 나란히 적어
    본문 첫 줄의 '문서명 > 섹션 경로' 가 콘솔 메뉴 경로로 오해되지 않게 하고,
    블록 끝에 그 청크의 스크린샷을 '[그림 N] 캡션' 으로 붙인다 (스펙 3-1).
    """
    image_map, per_cand = number_images(cands)
    blocks = []
    for i, (c, nums) in enumerate(zip(cands, per_cand), 1):
        doc_title = os.path.splitext(os.path.basename(c.source_path))[0]
        block = (
            f"[문서 {i}] 서비스: {c.service} · 문서: {doc_title} · "
            f"섹션: {c.section_path} · 출처: {c.source_url or c.source_path}\n{c.content}"
        )
        for n in nums:
            block += f"\n[그림 {n}] {image_map[n].caption}"
        blocks.append(block)

    context = "\n\n".join(blocks)
    prompt = f"""{format_history(history)}아래 문서를 근거로 질문에 답해라.

{context}

질문:
{question}
"""
    return prompt, image_map


def ask(question, history=None):
    q = retrieval_query(question, history)
    docs, _ = search_docs(q, service=None)
    prompt, _ = build_prompt(question, docs, history, intent=detect_intent(question))
    return chat(prompt, system=system_prompt(detect_intent(question)), max_tokens=2048)


def answer_stream(question, cands: list[Candidate], history=None, intent="general"):
    """(토큰 스트림, 그림 순번표). UI 가 스트리밍 뒤 순번표로 마커를 스크린샷으로 바꾼다."""
    prompt, image_map = build_prompt(question, cands, history, intent=intent)
    return chat_stream(prompt, system=system_prompt(intent), max_tokens=2048), image_map
```

5. `eval/bench_latency.py` 50~52행을 새 시그니처로:

```python
        docs, grounded = rag.rerank_candidates(q, cands); t2 = time.time()
        prompt, _ = rag.build_prompt(q, docs, intent=intent)
        ans = llm.chat(prompt, system=rag.system_prompt(intent), max_tokens=2048); t3 = time.time()
```

(파일의 `intent` 변수는 이미 그 위에서 `rag.detect_intent(q)`로 정의돼 있다. 없으면 같은 줄에 추가한다.)

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest -q`
Expected: 전부 PASS (삭제한 4개만큼 줄고 추가한 만큼 늘어남). `ui.py`는 아직 옛 API를 쓰지만 테스트에서 import 되지 않으므로 이 단계에선 깨지지 않는다 (Task 5에서 교체).

- [ ] **Step 5: 커밋**

```bash
git add app/rag.py app/tests/test_search_units.py eval/bench_latency.py
git commit -m "feat(rag): Candidate 기반 프롬프트에 그림 순번표·의도별 시스템 프롬프트, 문자열 호환 경로 제거

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: `answer_render` — 마커 분할 순수 모듈

**Files:**
- Create: `app/answer_render.py`
- Test: `app/tests/test_answer_render.py`

**Interfaces:**
- Consumes: `rag.ImageRef`.
- Produces:
  - `MARKER = re.compile(r"\{\{img:(\d+)\}\}")`
  - `NOT_GROUNDED_MESSAGE = "제공된 문서에서 확인되지 않습니다."`
  - `split_markers(text: str, image_map: dict[int, ImageRef]) -> list[tuple[str, str | ImageRef]]` — `("text", str)` 또는 `("image", ImageRef)`. 범위 밖 마커는 제거 + stderr.
  - `valid_markers(text, image_map) -> list[int]` — 본문에 등장한 마커 중 순번표에 있는 번호(순서·중복 유지). 평가 스크립트(2B-2)와 UI가 쓴다.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
"""{{img:N}} 마커 분할. Streamlit 없이 순수 함수만 검사한다."""
import answer_render as ar
from rag import ImageRef

MAP = {1: ImageRef("p/1.png", "하나"), 2: ImageRef("p/2.png", "둘")}


def test_split_text_without_markers_is_single_text_part():
    assert ar.split_markers("그냥 글", MAP) == [("text", "그냥 글")]


def test_split_alternates_text_and_images_in_order():
    parts = ar.split_markers("1. 클릭 {{img:1}}\n2. 저장 {{img:2}}", MAP)
    assert parts == [
        ("text", "1. 클릭 "),
        ("image", MAP[1]),
        ("text", "\n2. 저장 "),
        ("image", MAP[2]),
    ]


def test_split_drops_out_of_range_marker_and_logs(capsys):
    parts = ar.split_markers("앞 {{img:9}} 뒤", MAP)
    assert parts == [("text", "앞 "), ("text", " 뒤")]
    assert "img:9" in capsys.readouterr().err


def test_split_handles_marker_at_edges_and_empty_map():
    assert ar.split_markers("{{img:1}}", MAP) == [("image", MAP[1])]
    assert ar.split_markers("{{img:1}} 끝", {}) == [("text", " 끝")]
    assert ar.split_markers("", MAP) == []


def test_valid_markers_keeps_order_and_repeats_but_not_out_of_range():
    assert ar.valid_markers("{{img:2}} a {{img:1}} b {{img:2}} c {{img:7}}", MAP) == [2, 1, 2]
    assert ar.valid_markers("마커 없음", MAP) == []


def test_not_grounded_message_is_fixed():
    assert ar.NOT_GROUNDED_MESSAGE == "제공된 문서에서 확인되지 않습니다."
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest app/tests/test_answer_render.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'answer_render'`

- [ ] **Step 3: 구현**

```python
"""답변 본문의 {{img:N}} 마커를 텍스트/이미지 조각으로 나눈다 (스펙 3-4).

Streamlit 을 import 하지 않는다 — UI 와 평가 스크립트가 같이 쓰는 순수 함수다.
"""
import re
import sys

from rag import ImageRef

MARKER = re.compile(r"\{\{img:(\d+)\}\}")

# grounded == False 일 때 LLM 을 부르지 않고 그대로 보여 주는 문구 (스펙 3-3).
NOT_GROUNDED_MESSAGE = "제공된 문서에서 확인되지 않습니다."


def split_markers(text: str, image_map: dict[int, ImageRef]) -> list[tuple[str, str | ImageRef]]:
    """[("text", 문자열) | ("image", ImageRef)] 순서 목록. 순번표에 없는 번호는 지우고 stderr 에 남긴다."""
    parts: list[tuple[str, str | ImageRef]] = []
    pos = 0
    for m in MARKER.finditer(text):
        before = text[pos:m.start()]
        if before:
            parts.append(("text", before))
        n = int(m.group(1))
        ref = image_map.get(n)
        if ref is None:
            print(f"  [스크린샷] 순번표 밖 마커 {{{{img:{n}}}}} 제거 (그림 {len(image_map)}장)", file=sys.stderr)
        else:
            parts.append(("image", ref))
        pos = m.end()
    tail = text[pos:]
    if tail:
        parts.append(("text", tail))
    return parts


def valid_markers(text: str, image_map: dict[int, ImageRef]) -> list[int]:
    """본문에 나온 마커 번호 중 순번표에 있는 것만, 등장 순서대로."""
    return [int(n) for n in MARKER.findall(text) if int(n) in image_map]
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest app/tests/test_answer_render.py -q`
Expected: 6 passed

- [ ] **Step 5: 커밋**

```bash
git add app/answer_render.py app/tests/test_answer_render.py
git commit -m "feat(answer_render): {{img:N}} 마커 분할과 고정 미확인 문구

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: `db.migrate` 컬럼 추가와 `qlog` 질문 로그·피드백

**Files:**
- Modify: `app/db.py` (`init_schema` 끝, 새 함수 `migrate`)
- Create: `app/qlog.py`
- Create: `app/tests/conftest.py` (`test_db` 픽스처 이동)
- Modify: `app/tests/test_ingest_db.py` (픽스처 정의 삭제)
- Test: `app/tests/test_qlog_db.py` (통합)

**Interfaces:**
- Consumes: `db.get_conn`, `db._table_exists`, `rag.Candidate`.
- Produces:
  - `db.QUESTION_COLUMNS = (("session_id", "TEXT"), ("answer", "TEXT"), ("retrieval_query", "TEXT"))`
  - `db.migrate(conn) -> None` — 테이블이 있을 때만 `ADD COLUMN IF NOT EXISTS`, commit.
  - `qlog.sources_of(cands) -> list[dict]` — `[{source_path, section_path, source_url, service}]`
  - `qlog.log_question(*, session_id, question, retrieval_query, service, intent, grounded, elapsed_ms, sources, answer, error=None) -> int | None`
  - `qlog.set_feedback(question_id: int, value: int) -> bool`

- [ ] **Step 1: 픽스처를 conftest 로 옮긴다**

`app/tests/conftest.py` 신규:

```python
"""통합 테스트 공용 픽스처. 실데이터 DB(ragdb)를 건드리지 않도록 ragdb_test 를 쓴다."""
import pytest


@pytest.fixture(scope="session")
def test_db():
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
```

`app/tests/test_ingest_db.py`에서 `test_db`·`conn` 픽스처 정의(두 `@pytest.fixture` 블록)를 삭제한다. `test_uses_test_database`는 그대로 둔다.

- [ ] **Step 2: 실패하는 통합 테스트 작성** — `app/tests/test_qlog_db.py`

```python
"""questions 로그·피드백·컬럼 추가. 실제 pgvector 필요:  DB_HOST=localhost python -m pytest -m integration app/tests/test_qlog_db.py"""
import pytest

pytestmark = pytest.mark.integration


@pytest.fixture
def schema(conn):
    import db
    db.init_schema(conn, dim=8, rebuild=True)
    cur = conn.cursor()
    cur.execute("DELETE FROM questions")
    conn.commit()
    cur.close()
    return conn


def columns(conn, table):
    cur = conn.cursor()
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = %s", (table,))
    out = {r[0] for r in cur.fetchall()}
    cur.close()
    return out


def test_init_schema_adds_2b_columns(schema):
    assert {"session_id", "answer", "retrieval_query"} <= columns(schema, "questions")
    assert "ingested_at" in columns(schema, "documents")


def test_migrate_is_idempotent(schema):
    import db
    db.migrate(schema)
    db.migrate(schema)
    assert "session_id" in columns(schema, "questions")


def test_migrate_skips_when_tables_missing(conn):
    """questions 가 없는 빈 DB 에서도 UI 기동이 죽지 않는다."""
    import db
    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS questions")
    cur.execute("DROP TABLE IF EXISTS documents")
    conn.commit()
    cur.close()
    db.migrate(conn)  # 예외 없이 끝나면 통과


def test_log_question_inserts_and_returns_id(schema):
    import qlog
    from rag import Candidate
    c = Candidate(content="본문", source_path="Network/VPC/콘솔 사용 가이드.html", service="Network/VPC",
                  doc_type="console", score=1.0, section_path="서브넷 생성", source_url="https://x/")

    qid = qlog.log_question(session_id="s1", question="서브넷?", retrieval_query="서브넷?", service="Network/VPC",
                            intent="console", grounded=True, elapsed_ms=1234, sources=qlog.sources_of([c]),
                            answer="콘솔 > Network > VPC")

    assert isinstance(qid, int)
    cur = schema.cursor()
    cur.execute("SELECT session_id, question, service, intent, grounded, elapsed_ms, sources, answer, error, feedback "
                "FROM questions WHERE id = %s", (qid,))
    row = cur.fetchone()
    cur.close()
    assert row[0] == "s1" and row[1] == "서브넷?" and row[2] == "Network/VPC" and row[3] == "console"
    assert row[4] is True and row[5] == 1234
    assert row[6] == [{"source_path": "Network/VPC/콘솔 사용 가이드.html", "section_path": "서브넷 생성",
                       "source_url": "https://x/", "service": "Network/VPC"}]
    assert row[7] == "콘솔 > Network > VPC" and row[8] is None and row[9] is None


def test_log_question_records_error_and_null_grounded(schema):
    import qlog
    qid = qlog.log_question(session_id="s1", question="q", retrieval_query="q", service=None, intent="general",
                            grounded=None, elapsed_ms=10, sources=[], answer="", error="RateLimitError: 429")
    cur = schema.cursor()
    cur.execute("SELECT grounded, error, service FROM questions WHERE id = %s", (qid,))
    assert cur.fetchone() == (None, "RateLimitError: 429", None)
    cur.close()


def test_set_feedback_updates_row(schema):
    import qlog
    qid = qlog.log_question(session_id="s", question="q", retrieval_query="q", service=None, intent="general",
                            grounded=True, elapsed_ms=1, sources=[], answer="a")
    assert qlog.set_feedback(qid, -1) is True
    cur = schema.cursor()
    cur.execute("SELECT feedback FROM questions WHERE id = %s", (qid,))
    assert cur.fetchone()[0] == -1
    cur.close()


def test_log_failures_do_not_raise(monkeypatch, capsys):
    import qlog

    def boom():
        raise RuntimeError("DB 죽음")

    monkeypatch.setattr(qlog, "get_conn", boom)
    assert qlog.log_question(session_id="s", question="q", retrieval_query="q", service=None, intent="general",
                             grounded=True, elapsed_ms=1, sources=[], answer="a") is None
    assert qlog.set_feedback(1, 1) is False
    assert "질문 로그" in capsys.readouterr().err
```

- [ ] **Step 3: 실패 확인**

Run: `DB_HOST=localhost python -m pytest -m integration app/tests/test_qlog_db.py -q`
Expected: FAIL — `ModuleNotFoundError: qlog`, `db.migrate` 없음. (PowerShell: `$env:DB_HOST='localhost'; python -m pytest -m integration app/tests/test_qlog_db.py -q`)

- [ ] **Step 4: 구현**

`app/db.py` — `init_schema` 안 `conn.commit()` 직전(questions CREATE 다음)에 `migrate(conn)` 호출을 넣고, 파일 끝에 추가:

```python
# 2단계-B 에서 늘어난 컬럼. 재적재 없이 UI 기동 때 붙인다 (스펙 4-2).
QUESTION_COLUMNS = (
    ("session_id", "TEXT"),        # 브라우저 세션당 랜덤 UUID — 신원이 아니라 사용자 수 추정용
    ("answer", "TEXT"),            # 👎 검토용 답변 전문
    ("retrieval_query", "TEXT"),   # 대화 맥락을 합친 검색 질의
)


def migrate(conn) -> None:
    """questions·documents 에 2B 컬럼을 멱등하게 추가한다. 테이블이 없으면 아무것도 하지 않는다."""
    cur = conn.cursor()
    if _table_exists(cur, "questions"):
        for col, typ in QUESTION_COLUMNS:
            cur.execute(f"ALTER TABLE questions ADD COLUMN IF NOT EXISTS {col} {typ}")
    if _table_exists(cur, "documents"):
        cur.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS ingested_at TIMESTAMPTZ DEFAULT now()")
    conn.commit()
    cur.close()
```

`init_schema`의 questions CREATE 뒤, `conn.commit()` 앞에 `cur.close()` 없이 `migrate(conn)`를 부르면 커서가 두 개가 되므로: questions CREATE 직후 `conn.commit(); cur.close()` 를 먼저 하고 마지막 줄로 `migrate(conn)` 를 호출한다.

`app/qlog.py` 신규:

```python
"""질문 로그(questions)와 👍/👎 피드백 (스펙 4-2).

실패해도 화면을 깨뜨리지 않는다: 예외는 stderr 에만 남기고 None/False 를 돌려준다.
사용자 식별 정보는 저장하지 않는다.
"""
import json
import sys

from db import get_conn


def sources_of(cands) -> list[dict]:
    """questions.sources 에 넣을 모양. Candidate 목록에서 출처 네 항목만 뽑는다."""
    return [
        {"source_path": c.source_path, "section_path": c.section_path,
         "source_url": c.source_url, "service": c.service}
        for c in cands
    ]


def log_question(*, session_id, question, retrieval_query, service, intent, grounded,
                 elapsed_ms, sources, answer, error=None) -> int | None:
    """한 행을 넣고 id 를 돌려준다. 실패하면 None."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO questions (session_id, question, retrieval_query, service, intent, grounded, "
            "elapsed_ms, sources, answer, error) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (session_id, question, retrieval_query, service, intent, grounded, int(elapsed_ms),
             json.dumps(sources, ensure_ascii=False), answer, error),
        )
        qid = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()
        return qid
    except Exception as e:
        print(f"  [질문 로그 실패] {type(e).__name__}: {e}", file=sys.stderr)
        return None


def set_feedback(question_id: int, value: int) -> bool:
    """feedback 을 +1/-1 로 갱신한다. 실패하면 False."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("UPDATE questions SET feedback = %s WHERE id = %s", (value, question_id))
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"  [질문 로그 실패] 피드백 저장: {type(e).__name__}: {e}", file=sys.stderr)
        return False
```

- [ ] **Step 5: 통과 확인**

Run: `DB_HOST=localhost python -m pytest -m integration app/tests/test_qlog_db.py app/tests/test_ingest_db.py -q`
Expected: qlog 7 passed, ingest_db 기존 4 passed (픽스처 이동 후에도). 그리고 `python -m pytest -q` 단위 전부 PASS.

- [ ] **Step 6: 커밋**

```bash
git add app/db.py app/qlog.py app/tests/conftest.py app/tests/test_ingest_db.py app/tests/test_qlog_db.py
git commit -m "feat(qlog): questions 로그·피드백과 2B 컬럼 멱등 추가

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: `admin_stats` — 관리자 집계 SQL

**Files:**
- Create: `app/admin_stats.py`
- Test: `app/tests/test_admin_stats_db.py` (통합)

**Interfaces:**
- Consumes: `questions`(Task 3 컬럼 포함), `documents.ingested_at`.
- Produces (모두 `conn`을 첫 인자로 받고 커서를 열고 닫는다; `since: datetime | None`, None 이면 전체):
  - `PERIODS = ("7일", "30일", "전체")`, `since_for(period: str) -> datetime | None`
  - `summary(conn, since) -> dict` — 키 `questions, sessions, median_s, max_s, error_rate, ungrounded_rate, up, down` (비율은 0~1 float, 질문 0건이면 0.0; 초는 float)
  - `by_service(conn, since) -> list[tuple[str, int, int, int]]` — (service, 질문 수, 👎 수, 미확인 수), 👎 내림차순·질문 수 내림차순. `service` NULL 은 `"(미상)"`.
  - `recent_down(conn, since, limit=20) -> list[tuple[datetime, str, str | None, str]]` — (asked_at, question, service, answer 앞 200자)
  - `recent_ungrounded(conn, since, limit=20) -> list[tuple[datetime, str, str | None]]`
  - `recent_slow(conn, since, limit=20, threshold_ms=30000) -> list[tuple[datetime, str, int]]`
  - `index_status(conn) -> dict` — `chunks, services, last_ingested_at`

- [ ] **Step 1: 실패하는 통합 테스트 작성** — `app/tests/test_admin_stats_db.py`

```python
"""관리자 집계. 실제 pgvector 필요:  DB_HOST=localhost python -m pytest -m integration app/tests/test_admin_stats_db.py"""
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.integration

NOW = datetime.now(timezone.utc)


def insert(conn, **kw):
    row = dict(asked_at=NOW, session_id="s", question="q", service="Network/VPC", intent="console",
               grounded=True, elapsed_ms=1000, sources="[]", answer="a", error=None, feedback=None)
    row.update(kw)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO questions (asked_at, session_id, question, service, intent, grounded, elapsed_ms, sources, "
        "answer, error, feedback) VALUES (%(asked_at)s, %(session_id)s, %(question)s, %(service)s, %(intent)s, "
        "%(grounded)s, %(elapsed_ms)s, %(sources)s, %(answer)s, %(error)s, %(feedback)s)", row)
    conn.commit()
    cur.close()


@pytest.fixture
def seeded(conn):
    import db
    db.init_schema(conn, dim=8, rebuild=True)
    cur = conn.cursor()
    cur.execute("DELETE FROM questions")
    conn.commit()
    cur.close()
    insert(conn, session_id="a", elapsed_ms=1000, feedback=1)
    insert(conn, session_id="a", elapsed_ms=3000, feedback=-1, answer="긴 답변" * 100)
    insert(conn, session_id="b", elapsed_ms=40000, grounded=False, service="Storage/Object Storage")
    insert(conn, session_id="b", elapsed_ms=500, error="RateLimitError", grounded=None, service=None)
    insert(conn, session_id="c", elapsed_ms=2000, asked_at=NOW - timedelta(days=10), feedback=-1)
    return conn


def test_since_for_periods():
    import admin_stats as s
    assert s.since_for("전체") is None
    assert abs((datetime.now(timezone.utc) - s.since_for("7일")).days - 7) <= 0
    assert abs((datetime.now(timezone.utc) - s.since_for("30일")).days - 30) <= 0


def test_summary_all(seeded):
    import admin_stats as s
    r = s.summary(seeded, None)
    assert r["questions"] == 5 and r["sessions"] == 3
    assert r["median_s"] == 2.0 and r["max_s"] == 40.0
    assert r["error_rate"] == pytest.approx(0.2)
    assert r["ungrounded_rate"] == pytest.approx(0.2)
    assert r["up"] == 1 and r["down"] == 2


def test_summary_last_7_days_excludes_old_row(seeded):
    import admin_stats as s
    r = s.summary(seeded, s.since_for("7일"))
    assert r["questions"] == 4 and r["down"] == 1


def test_summary_empty_period_is_zero_not_error(seeded):
    import admin_stats as s
    r = s.summary(seeded, datetime.now(timezone.utc) + timedelta(days=1))
    assert r == {"questions": 0, "sessions": 0, "median_s": 0.0, "max_s": 0.0,
                 "error_rate": 0.0, "ungrounded_rate": 0.0, "up": 0, "down": 0}


def test_by_service_orders_by_down_then_count(seeded):
    import admin_stats as s
    rows = s.by_service(seeded, None)
    assert rows[0] == ("Network/VPC", 3, 2, 0)
    assert ("Storage/Object Storage", 1, 0, 1) in rows
    assert ("(미상)", 1, 0, 0) in rows


def test_recent_lists(seeded):
    import admin_stats as s
    down = s.recent_down(seeded, None)
    assert len(down) == 2 and len(down[0][3]) <= 200
    assert [r[1] for r in s.recent_ungrounded(seeded, None)] == ["q"]
    slow = s.recent_slow(seeded, None)
    assert len(slow) == 1 and slow[0][2] == 40000
    assert s.recent_down(seeded, None, limit=1) and len(s.recent_down(seeded, None, limit=1)) == 1


def test_index_status_reads_documents(seeded):
    import admin_stats as s
    r = s.index_status(seeded)
    assert r["chunks"] == 0 and r["services"] == 0 and r["last_ingested_at"] is None
```

- [ ] **Step 2: 실패 확인**

Run: `DB_HOST=localhost python -m pytest -m integration app/tests/test_admin_stats_db.py -q`
Expected: FAIL — `ModuleNotFoundError: admin_stats`

- [ ] **Step 3: 구현** — `app/admin_stats.py`

```python
"""관리자 페이지 집계 (스펙 4-3). questions 테이블만 읽는다. Streamlit 을 import 하지 않는다."""
from datetime import datetime, timedelta, timezone

PERIODS = ("7일", "30일", "전체")
SLOW_MS = 30000

# since 가 None 이면 전체 기간. 같은 파라미터를 두 번 넘겨 NULL 검사와 비교를 한 절로 처리한다.
_SINCE = "(%(since)s::timestamptz IS NULL OR asked_at >= %(since)s)"


def since_for(period: str) -> datetime | None:
    days = {"7일": 7, "30일": 30}.get(period)
    return None if days is None else datetime.now(timezone.utc) - timedelta(days=days)


def _rows(conn, sql, params):
    cur = conn.cursor()
    cur.execute(sql, params)
    out = cur.fetchall()
    cur.close()
    return out


def summary(conn, since) -> dict:
    (n, sessions, median_ms, max_ms, errors, ungrounded, up, down), = _rows(conn, f"""
        SELECT count(*),
               count(DISTINCT session_id),
               percentile_cont(0.5) WITHIN GROUP (ORDER BY elapsed_ms),
               max(elapsed_ms),
               count(*) FILTER (WHERE error IS NOT NULL),
               count(*) FILTER (WHERE grounded = false),
               count(*) FILTER (WHERE feedback = 1),
               count(*) FILTER (WHERE feedback = -1)
          FROM questions WHERE {_SINCE}""", {"since": since})
    n = int(n)
    return {
        "questions": n,
        "sessions": int(sessions),
        "median_s": round(float(median_ms or 0) / 1000, 1),
        "max_s": round(float(max_ms or 0) / 1000, 1),
        "error_rate": (int(errors) / n) if n else 0.0,
        "ungrounded_rate": (int(ungrounded) / n) if n else 0.0,
        "up": int(up),
        "down": int(down),
    }


def by_service(conn, since) -> list[tuple[str, int, int, int]]:
    rows = _rows(conn, f"""
        SELECT coalesce(service, '(미상)'),
               count(*),
               count(*) FILTER (WHERE feedback = -1),
               count(*) FILTER (WHERE grounded = false)
          FROM questions WHERE {_SINCE}
         GROUP BY 1 ORDER BY 3 DESC, 2 DESC, 1""", {"since": since})
    return [(r[0], int(r[1]), int(r[2]), int(r[3])) for r in rows]


def recent_down(conn, since, limit=20):
    return _rows(conn, f"""
        SELECT asked_at, question, service, left(coalesce(answer, ''), 200)
          FROM questions WHERE {_SINCE} AND feedback = -1
         ORDER BY asked_at DESC LIMIT %(limit)s""", {"since": since, "limit": limit})


def recent_ungrounded(conn, since, limit=20):
    return _rows(conn, f"""
        SELECT asked_at, question, service
          FROM questions WHERE {_SINCE} AND grounded = false
         ORDER BY asked_at DESC LIMIT %(limit)s""", {"since": since, "limit": limit})


def recent_slow(conn, since, limit=20, threshold_ms=SLOW_MS):
    return _rows(conn, f"""
        SELECT asked_at, question, elapsed_ms
          FROM questions WHERE {_SINCE} AND elapsed_ms > %(threshold)s
         ORDER BY asked_at DESC LIMIT %(limit)s""", {"since": since, "limit": limit, "threshold": threshold_ms})


def index_status(conn) -> dict:
    (chunks, services, last), = _rows(
        conn, "SELECT count(*), count(DISTINCT service), max(ingested_at) FROM documents", {})
    return {"chunks": int(chunks), "services": int(services), "last_ingested_at": last}
```

- [ ] **Step 4: 통과 확인**

Run: `DB_HOST=localhost python -m pytest -m integration app/tests/test_admin_stats_db.py -q`
Expected: 7 passed

- [ ] **Step 5: 커밋**

```bash
git add app/admin_stats.py app/tests/test_admin_stats_db.py
git commit -m "feat(admin_stats): 관리자 페이지 집계 SQL

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: 챗 화면 재작성 — `chat_page.py` + `ui.py` 셸 + CSS

**Files:**
- Create: `app/chat_page.py`
- Modify: `app/ui.py` (셸만 남김)
- Modify: `app/styles.py` (클래스 3개 추가)
- Test: `app/tests/test_ui_apptest.py`

**Interfaces:**
- Consumes: Task 1 `rag.answer_stream/rerank_candidates/hybrid_search/detect_intent/detect_service/retrieval_query/ALIASES/ImageRef`, Task 2 `answer_render.split_markers/NOT_GROUNDED_MESSAGE`, Task 3 `qlog.log_question/set_feedback/sources_of`, `db.migrate`.
- Produces:
  - `chat_page.page()` — `st.navigation`용 페이지 함수.
  - `chat_page.load_index()` (`@st.cache_resource`) — `(rag 모듈, 청크 수)`; 안에서 `db.migrate` 호출.
  - `chat_page.render_answer(text, image_map)`, `chat_page.DOCS_DIR`, `chat_page.EXAMPLES`.
  - `ui.py`는 Task 6이 `admin_page.page`를 `st.Page`로 추가할 자리를 갖는다.

세션 메시지 구조 (assistant): `{"role": "assistant", "content": str, "cands": list[Candidate], "image_map": dict[int, ImageRef], "service": str | None, "intent": str, "question_id": int | None, "error": bool}`. `rag.format_history`는 `content`·`error`만 읽는다.

- [ ] **Step 1: 실패하는 AppTest 작성** — `app/tests/test_ui_apptest.py`

```python
"""Streamlit AppTest 로 챗 화면 배선을 검사한다. DB·LLM 은 전부 가짜다."""
import types

import pytest
from streamlit.testing.v1 import AppTest

import rag
from rag import Candidate, ImageRef


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
    at = AppTest.from_file("app/ui.py", default_timeout=30)
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
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest app/tests/test_ui_apptest.py -q`
Expected: FAIL — `ModuleNotFoundError: chat_page` (또는 `ui.py`가 옛 API를 불러 예외).

- [ ] **Step 3: CSS 추가** — `app/styles.py`의 `.nhn-service-tag` 블록 뒤에:

```css
.nhn-answer-tag { margin: 0 0 0.5rem 0; }
.nhn-source-row { margin-bottom: 0.6rem; display: flex; flex-wrap: wrap; align-items: center; gap: 0.2rem; }
.nhn-source-chip a { color: inherit; text-decoration: none; }
.nhn-source-chip a:hover { text-decoration: underline; }
.nhn-section { font-size: 0.72rem; color: var(--nhn-gray-700); margin-left: 0.3rem; }
```

- [ ] **Step 4: `chat_page.py` 작성**

```python
"""챗 화면 (스펙 3·4-1). ui.py 의 st.navigation 이 page() 를 부른다."""
import os
import sys
import time
import uuid

import streamlit as st

import answer_render as ar
import db
import qlog

# 컨테이너에서는 /docs, 로컬에서는 저장소 루트의 nhn_cloud_docs.
DOCS_DIR = os.getenv(
    "DOCS_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "nhn_cloud_docs"),
)

EXAMPLES = [
    "VPC에 서브넷을 추가하는 방법",
    "로드 밸런서를 생성하는 절차",
    "플로팅 IP를 인스턴스에 연결하는 방법",
    "Object Storage에 컨테이너를 만드는 방법",
]
INTENT_LABEL = {"console": "콘솔 절차", "general": "일반"}
AUTO = "자동"
CANDIDATES = 20  # 벡터·BM25 각각 가져올 개수 (슬라이더 제거, 고정)
USER_MARKER = '<span class="nhn-user-marker"></span>'


@st.cache_resource(show_spinner=False)
def load_index():
    """BM25 인덱스는 프로세스당 한 번. 같은 자리에서 2B 컬럼도 붙인다 (재적재 없이)."""
    import rag

    conn = db.get_conn()
    try:
        db.migrate(conn)
    finally:
        conn.close()
    count = rag.build_bm25()
    return rag, count


# ---------------------------------------------------------------- 그리기

def user_bubble(text):
    with st.chat_message("user", avatar="🙋"):
        st.markdown(USER_MARKER, unsafe_allow_html=True)
        st.markdown(text)


def service_tag(service, intent):
    st.markdown(
        f'<div class="nhn-answer-tag"><span class="nhn-service-tag">{service or "서비스 미상"}</span>'
        f'<span class="nhn-source-chip">{INTENT_LABEL.get(intent, intent)}</span></div>',
        unsafe_allow_html=True,
    )


def render_answer(text, image_map):
    """{{img:N}} 을 스크린샷으로 바꿔 그린다. 파일이 없으면 그 그림만 건너뛴다 (스펙 6절)."""
    for kind, part in ar.split_markers(text, image_map or {}):
        if kind == "text":
            st.markdown(part)
            continue
        full = os.path.join(DOCS_DIR, part.path)
        if os.path.isfile(full):
            st.image(full, caption=part.caption or None)
        else:
            print(f"  [스크린샷] 파일 없음: {full}", file=sys.stderr)


def render_sources(cands):
    if not cands:
        return
    with st.expander(f"참고한 문서 {len(cands)}건", expanded=False):
        for i, c in enumerate(cands, 1):
            name = os.path.splitext(os.path.basename(c.source_path))[0]
            label = f'<a href="{c.source_url}" target="_blank">{i}. {name}</a>' if c.source_url else f"{i}. {name}"
            st.markdown(
                f'<div class="nhn-source-row"><span class="nhn-service-tag">{c.service}</span>'
                f'<span class="nhn-source-chip">{label}</span>'
                f'<span class="nhn-section">{c.section_path}</span></div>',
                unsafe_allow_html=True,
            )


def feedback_buttons(idx, question_id):
    """👍/👎. 누르면 바로 저장하고 자리에 결과 문구를 남긴다."""
    key = f"fb_{idx}"
    if key in st.session_state:
        st.caption(st.session_state[key])
        return
    if question_id is None:
        return
    up, down, _ = st.columns([1, 1, 8])
    if up.button("👍", key=f"{key}_up"):
        _save_feedback(key, question_id, 1)
    if down.button("👎", key=f"{key}_down"):
        _save_feedback(key, question_id, -1)


def _save_feedback(key, question_id, value):
    st.session_state[key] = "의견 감사합니다" if qlog.set_feedback(question_id, value) else "저장 실패"
    st.rerun()


def render_assistant(idx, msg):
    with st.chat_message("assistant", avatar="☁️"):
        service_tag(msg.get("service"), msg.get("intent", "general"))
        if msg.get("grounded") is None and not msg.get("error"):
            st.caption("관련도 확인 실패 — 검색 순서를 그대로 사용했습니다.")
        render_answer(msg["content"], msg.get("image_map"))
        if msg.get("grounded") is not False:
            render_sources(msg.get("cands") or [])
        feedback_buttons(idx, msg.get("question_id"))


# ---------------------------------------------------------------- 페이지

def page():
    st.markdown(
        '<div class="nhn-header"><div class="nhn-logo">NHN</div>'
        '<div><div class="nhn-title">NHN Cloud 콘솔 안내 봇</div>'
        '<div class="nhn-subtitle">공식 문서를 근거로 콘솔 사용법을 안내합니다</div></div></div>',
        unsafe_allow_html=True,
    )

    try:
        rag, doc_count = load_index()
        ready, load_error = True, None
    except Exception as e:
        rag, doc_count, ready, load_error = None, 0, False, e

    with st.sidebar:
        st.markdown("### 인덱스")
        st.markdown(
            f'<div class="nhn-kv"><span>상태</span><span>{"연결됨" if ready else "연결 실패"}</span></div>'
            + (f'<div class="nhn-kv"><span>문서 청크</span><span>{doc_count:,}</span></div>' if ready else ""),
            unsafe_allow_html=True,
        )
        st.markdown("### 모델")
        from llm import EMBEDDING_MODEL_NAME, LLM_MODEL_NAME
        st.markdown(
            f'<div class="nhn-kv"><span>생성</span><span>{LLM_MODEL_NAME.split("/")[-1]}</span></div>'
            f'<div class="nhn-kv"><span>임베딩</span><span>{EMBEDDING_MODEL_NAME.split("/")[-1]}</span></div>',
            unsafe_allow_html=True,
        )
        st.markdown("### 검색 설정")
        services = sorted(set(rag.ALIASES.values())) if ready else []
        chosen = st.selectbox("서비스", [AUTO] + services, help="자동이면 질문에서 서비스를 추정합니다.")
        top_k = st.slider("참고 문서 수", 3, 10, 5)
        st.divider()
        if st.button("대화 초기화", use_container_width=True):
            st.session_state.messages = []
            st.session_state.pop("last_service", None)
            st.rerun()

    if not ready:
        st.error("문서 인덱스에 연결하지 못했습니다. DB 와 적재 상태를 확인하세요.")
        st.caption(f"상세: {type(load_error).__name__}: {load_error}")
        st.stop()

    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("pending", None)
    st.session_state.setdefault("session_id", uuid.uuid4().hex)

    if not st.session_state.messages:
        st.markdown(
            '<div class="nhn-empty"><h2>무엇을 도와드릴까요?</h2>'
            "<p>콘솔에서 어떻게 하는지 물어보세요. 메뉴 경로와 화면을 함께 안내합니다.</p></div>",
            unsafe_allow_html=True,
        )
        cols = st.columns(2)
        for i, ex in enumerate(EXAMPLES):
            if cols[i % 2].button(ex, key=f"ex_{i}", use_container_width=True):
                st.session_state.pending = ex
                st.rerun()

    for idx, msg in enumerate(st.session_state.messages):
        if msg["role"] == "user":
            user_bubble(msg["content"])
        else:
            render_assistant(idx, msg)

    typed = st.chat_input("NHN Cloud 콘솔 사용법을 질문하세요")
    question = typed or st.session_state.pending
    st.session_state.pending = None
    if question:
        answer_question(rag, question, chosen, top_k)


def answer_question(rag, question, chosen, top_k):
    history = list(st.session_state.messages)
    st.session_state.messages.append({"role": "user", "content": question})
    user_bubble(question)

    t0 = time.time()
    cands, image_map, grounded = [], {}, None
    service, intent, search_q = None, "general", question
    answer, failed, error_text = "", False, None

    with st.chat_message("assistant", avatar="☁️"):
        try:
            with st.status("문서를 검색하고 있습니다…", expanded=False) as status:
                search_q = rag.retrieval_query(question, history)
                intent = rag.detect_intent(question)
                if chosen != AUTO:
                    service = chosen
                else:
                    service = rag.detect_service(search_q, rag.ALIASES, fallback=st.session_state.get("last_service"))
                st.session_state.last_service = service
                status.update(label=f"1/3 하이브리드 검색 · {INTENT_LABEL[intent]} · {service or '서비스 미상'}")
                found = rag.hybrid_search(search_q, intent=intent, service=service, top_k=CANDIDATES)
                status.update(label=f"2/3 관련도 평가 ({len(found)}건)")
                cands, grounded = rag.rerank_candidates(search_q, found, top_k=top_k)
                status.update(label=f"3/3 답변 생성 · 검색 {time.time() - t0:.1f}초", state="complete")

            service_tag(service, intent)
            if grounded is False:
                # 근거 문서가 없으면 LLM 을 부르지 않는다 (스펙 3-3).
                answer = ar.NOT_GROUNDED_MESSAGE + (f" 관련 서비스: {service}" if service else "")
                cands = []
                st.markdown(answer)
            else:
                if grounded is None:
                    st.caption("관련도 확인 실패 — 검색 순서를 그대로 사용했습니다.")
                stream, image_map = rag.answer_stream(question, cands, history, intent=intent)
                holder = st.empty()
                with holder.container():
                    answer = st.write_stream(stream)
                holder.empty()
                with holder.container():
                    render_answer(answer, image_map)
                render_sources(cands)
        except Exception as e:
            answer = "⚠️ 모델 서버가 일시적으로 혼잡해 답변을 만들지 못했습니다. 잠시 후 다시 질문해 주세요."
            failed, error_text = True, f"{type(e).__name__}: {e}"
            cands, image_map = [], {}
            st.markdown(answer)
            st.caption(error_text)

        question_id = qlog.log_question(
            session_id=st.session_state.session_id, question=question, retrieval_query=search_q,
            service=service, intent=intent, grounded=grounded, elapsed_ms=int((time.time() - t0) * 1000),
            sources=qlog.sources_of(cands), answer=answer, error=error_text,
        )
        feedback_buttons(len(st.session_state.messages), question_id)

    st.session_state.messages.append({
        "role": "assistant", "content": answer, "cands": cands, "image_map": image_map,
        "service": service, "intent": intent, "grounded": grounded,
        "question_id": question_id, "error": failed,
    })
```

- [ ] **Step 5: `ui.py`를 셸로 교체**

```python
"""Streamlit 진입점. 화면은 chat_page / admin_page 에 있다."""
import streamlit as st

from styles import CSS

st.set_page_config(
    page_title="NHN Cloud 콘솔 안내 봇",
    page_icon="☁️",
    layout="centered",
    initial_sidebar_state="expanded",
)
st.markdown(CSS, unsafe_allow_html=True)

import chat_page  # noqa: E402  (set_page_config 가 먼저여야 한다)

PAGES = [
    st.Page(chat_page.page, title="챗", icon="💬", default=True),
]

st.navigation(PAGES).run()
```

(Task 6이 `admin_page`를 `PAGES`에 추가한다.)

- [ ] **Step 6: 통과 확인**

Run: `python -m pytest app/tests/test_ui_apptest.py -q` 그리고 `python -m pytest -q`
Expected: AppTest 3 passed, 전체 PASS. AppTest 에서 `st.write_stream`·`st.status`·`st.navigation`이 문제를 일으키면 실패 메시지를 그대로 보고에 적는다 (가짜 처리로 우회하지 말 것).

- [ ] **Step 7: 로컬 실행으로 눈 확인** (DB 가 떠 있을 때)

Run: `cd app && python -m streamlit run ui.py --server.headless true --server.port 8502` 를 백그라운드로 띄우고 `curl -s -o /dev/null -w "%{http_code}" http://localhost:8502/_stcore/health` 가 200 인지 확인 후 종료. 보고에 결과를 적는다.

- [ ] **Step 8: 커밋**

```bash
git add app/chat_page.py app/ui.py app/styles.py app/tests/test_ui_apptest.py
git commit -m "feat(ui): 챗 화면 분리 — 콘솔형 답변·인라인 스크린샷·서비스 선택·피드백·질문 로그

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: 관리자 페이지 `admin_page.py`

**Files:**
- Create: `app/admin_page.py`
- Modify: `app/ui.py` (`PAGES`에 추가)
- Test: `app/tests/test_ui_apptest.py` (테스트 1개 추가)

**Interfaces:**
- Consumes: Task 4 `admin_stats.*`, `db.get_conn`.
- Produces: `admin_page.page()`.

- [ ] **Step 1: 실패하는 AppTest 추가** — `app/tests/test_ui_apptest.py` 끝에:

```python
def test_admin_page_renders_metrics_with_fake_stats(monkeypatch):
    import admin_stats as s
    import admin_page

    monkeypatch.setattr(admin_page, "get_conn", lambda: object())
    monkeypatch.setattr(s, "summary", lambda conn, since: {
        "questions": 12, "sessions": 4, "median_s": 9.5, "max_s": 31.0,
        "error_rate": 0.25, "ungrounded_rate": 0.5, "up": 3, "down": 2})
    monkeypatch.setattr(s, "by_service", lambda conn, since: [("Network/VPC", 5, 2, 1)])
    monkeypatch.setattr(s, "recent_down", lambda conn, since, limit=20: [])
    monkeypatch.setattr(s, "recent_ungrounded", lambda conn, since, limit=20: [])
    monkeypatch.setattr(s, "recent_slow", lambda conn, since, limit=20, threshold_ms=30000: [])
    monkeypatch.setattr(s, "index_status", lambda conn: {"chunks": 100, "services": 7, "last_ingested_at": None})

    at = AppTest.from_function(admin_page.page, default_timeout=30)
    at.run()
    assert not at.exception
    assert any(m.value == "12" for m in at.metric)
    assert any("25%" in m.value for m in at.metric)
    assert any("Network/VPC" in str(d.value) for d in at.dataframe)
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest app/tests/test_ui_apptest.py::test_admin_page_renders_metrics_with_fake_stats -q`
Expected: FAIL — `ModuleNotFoundError: admin_page`

- [ ] **Step 3: 구현** — `app/admin_page.py`

```python
"""관리자 페이지 (스펙 4-3). questions 집계만 보여 준다. 인증은 없다 — 인증을 붙일 때 이 페이지부터 막는다."""
import pandas as pd
import streamlit as st

import admin_stats as s
from db import get_conn


def _pct(v: float) -> str:
    return f"{v * 100:.0f}%"


def page():
    st.markdown(
        '<div class="nhn-header"><div class="nhn-logo">NHN</div>'
        '<div><div class="nhn-title">관리자</div>'
        '<div class="nhn-subtitle">질문 로그·피드백 집계</div></div></div>',
        unsafe_allow_html=True,
    )
    period = st.radio("기간", s.PERIODS, horizontal=True, index=1)
    since = s.since_for(period)

    try:
        conn = get_conn()
    except Exception as e:
        st.error("DB 에 연결하지 못했습니다.")
        st.caption(f"{type(e).__name__}: {e}")
        return

    try:
        summary = s.summary(conn, since)
        services = s.by_service(conn, since)
        down = s.recent_down(conn, since)
        ungrounded = s.recent_ungrounded(conn, since)
        slow = s.recent_slow(conn, since)
        index = s.index_status(conn)
    finally:
        try:
            conn.close()
        except Exception:
            pass

    c = st.columns(4)
    c[0].metric("질문 수", f"{summary['questions']}")
    c[1].metric("세션 수", f"{summary['sessions']}")
    c[2].metric("응답 중앙값", f"{summary['median_s']}초")
    c[3].metric("응답 최대", f"{summary['max_s']}초")
    c = st.columns(4)
    c[0].metric("LLM 오류율", _pct(summary["error_rate"]))
    c[1].metric("미확인 비율", _pct(summary["ungrounded_rate"]))
    c[2].metric("👍", f"{summary['up']}")
    c[3].metric("👎", f"{summary['down']}")

    st.subheader("서비스별")
    st.dataframe(pd.DataFrame(services, columns=["서비스", "질문 수", "👎", "미확인"]),
                 use_container_width=True, hide_index=True)

    st.subheader("최근 👎 질문")
    st.dataframe(pd.DataFrame(down, columns=["시각", "질문", "서비스", "답변(앞 200자)"]),
                 use_container_width=True, hide_index=True)
    st.subheader("미확인으로 끝난 질문")
    st.dataframe(pd.DataFrame(ungrounded, columns=["시각", "질문", "서비스"]),
                 use_container_width=True, hide_index=True)
    st.subheader(f"{s.SLOW_MS // 1000}초 초과 질문")
    st.dataframe(pd.DataFrame(slow, columns=["시각", "질문", "소요(ms)"]),
                 use_container_width=True, hide_index=True)

    st.subheader("인덱스")
    last = index["last_ingested_at"]
    st.markdown(
        f'<div class="nhn-kv"><span>문서 청크</span><span>{index["chunks"]:,}</span></div>'
        f'<div class="nhn-kv"><span>서비스 수</span><span>{index["services"]}</span></div>'
        f'<div class="nhn-kv"><span>마지막 적재</span><span>{last.strftime("%Y-%m-%d %H:%M") if last else "기록 없음"}</span></div>',
        unsafe_allow_html=True,
    )
```

`pandas`는 Streamlit 의존성으로 이미 설치돼 있다. `app/requirements.txt`에 `pandas` 줄을 **추가하지 않는다** (Streamlit이 고정).

`app/ui.py`의 `PAGES`:

```python
import admin_page  # noqa: E402

PAGES = [
    st.Page(chat_page.page, title="챗", icon="💬", default=True),
    st.Page(admin_page.page, title="관리자", icon="📊", url_path="admin"),
]
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest app/tests/test_ui_apptest.py -q` 그리고 `python -m pytest -q`
Expected: 4 passed, 전체 PASS.

- [ ] **Step 5: 커밋**

```bash
git add app/admin_page.py app/ui.py app/tests/test_ui_apptest.py
git commit -m "feat(admin): 관리자 페이지 — 기간별 지표·서비스별 표·👎/미확인/느린 질문 목록

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: README 갱신과 클러스터 배포·눈 확인

**Files:**
- Modify: `README.md` (UI 절: 페이지 구성·서비스 선택·피드백·관리자 페이지·`DOCS_DIR`)
- Modify: `docs/superpowers/plans/2026-09-17-console-guide-bot-phase2-carryover.md` (2B-1 에서 처리한 항목 표시: `rerank` 래퍼 제거, `Candidate` 사용)

**Interfaces:** 없음 (문서와 배포).

- [ ] **Step 1: README 에 UI 절 갱신**

기존 UI 설명 절에 아래 내용을 문장으로 넣는다 (표는 자유):
- 페이지: 챗(`/`), 관리자(`/admin`). 관리자 페이지는 인증이 없다.
- 콘솔 절차 질문의 답변 형식: 첫 줄 메뉴 경로, 번호 단계, 단계 끝 스크린샷, 문서에 있을 때만 주의.
- 사이드바 서비스 선택(자동/고정), 참고 문서 수.
- 👍/👎 → `questions.feedback`. 질문마다 `questions` 1행(사용자 식별 정보 없음). 새 컬럼은 UI 기동 때 자동 추가.
- `DOCS_DIR`(기본 저장소 루트 `nhn_cloud_docs`, 컨테이너 `/docs`)에서 스크린샷을 읽는다.

- [ ] **Step 2: 이관 문서 갱신**

`2B 설계에 반영` 절의 첫 항목(`Candidate`가 …, `rerank` 래퍼 제거)에 `— 2B-1 에서 처리` 를 붙인다.

- [ ] **Step 3: 단위 테스트 전체 통과 확인**

Run: `python -m pytest -q`
Expected: 전부 PASS.

- [ ] **Step 4: 커밋**

```bash
git add README.md docs/superpowers/plans/2026-09-17-console-guide-bot-phase2-carryover.md
git commit -m "docs: 2B-1 UI 구성·피드백·관리자 페이지 안내

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

- [ ] **Step 5: 클러스터 배포 (컨트롤러가 수행 — 서브에이전트는 여기서 멈추고 보고한다)**

컨트롤러 절차 (README 의 k8s 런북 그대로):
1. `docker build -t harbor.114-110-181-178.nip.io/nnd/nhn-docs-bot:2b1-<git 짧은 해시> app/` → `docker push`.
2. `kubectl -n nhn-docs-bot set image deploy/ui ui=harbor.114-110-181-178.nip.io/nnd/nhn-docs-bot:2b1-<해시>` → `rollout status`.
3. `https://nhn-docs-bot.180-210-89-135.nip.io` 에서 콘솔 질문 3건(예시 질문 중 3개)으로 메뉴 경로·스크린샷·서비스 태그·👍/👎 확인, `/admin` 에서 지표 확인. 결과를 ledger 와 사용자 보고에 적는다.

---

## Self-review

**Spec coverage**
- 3-1 프롬프트 입력·순번표 → Task 1. 3-2 의도별 프롬프트 → Task 1. 3-3 grounded → Task 5 (`answer_question`). 3-4 렌더링·stderr → Task 2 + Task 5 `render_answer`. 3-5 출처 링크·래퍼 제거 → Task 1 + Task 5.
- 4-1 사이드바·태그·예시·피드백 → Task 5. 4-2 컬럼·기록 규칙 → Task 3. 4-3 관리자 → Task 4 + Task 6.
- 6절 오류 행(메뉴 경로 없음 → 프롬프트 문구 Task 1; 파일 없음 → Task 5; 로그 실패 → Task 3·5; 관리자 DB 실패 → Task 6) 모두 있음.
- 7-1 테스트: 마커 분할(Task 2), build_prompt(Task 1), 집계 SQL·로그(Task 3·4 통합), AppTest(Task 5·6). 크롤러 `build_driver` 테스트는 2B-2 계획에 속한다.
- 7-2 2B-1 완료 기준 → Task 7 Step 5.

**Placeholder scan** — "적절히", "TBD", "유사하게" 없음.

**Type consistency** — `build_prompt` 반환 `(str, dict[int, ImageRef])`를 Task 1·5·bench 가 동일하게 씀. `answer_stream` 반환 `(stream, image_map)` Task 1·5 일치. `qlog.log_question` 키워드 인자 목록이 Task 3 정의·Task 5 호출·AppTest 가짜에서 동일. `admin_stats` 함수 시그니처가 Task 4 정의·Task 6 호출·AppTest 가짜에서 동일(`recent_slow(conn, since, limit=20, threshold_ms=30000)`). `Candidate.images` 는 dict 목록(2A 계약) — `number_images` 가 `img.get(...)` 로 읽음.
