# 2C UI 고도화 구현 계획 — 답변 읽기 경험·대화 관리·관리자 시각화

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 답변을 읽는 경험을 다듬고(진행 표시 칩, 스크린샷 크게 보기, 인용 번호 + 출처 카드, 다시 생성, 첫 화면), 세션 안 대화 목록과 관리자 시각화(일별 추이·👎 답변 펼치기·질문 검색)를 더한다. Streamlit 안에서 끝낸다.

**Architecture:** `chat_page.py` 의 그리기 함수(`render_sources`, `render_answer`, `feedback_buttons`)와 `answer_question` 을 손보고, 대화 목록은 `st.session_state.conversations` 위에 얹는다(로그 스키마 변경 없음). 관리자는 `admin_stats` 에 `daily`/`search` 쿼리를 추가하고 `admin_page` 가 차트·expander·검색을 그린다. 프롬프트 변경은 `rag.py` 의 공통 시스템 프롬프트에 인용 지시 한 문장.

**Tech Stack:** Python 3.12, Streamlit 1.64 (`st.status`, `st.dialog`, `st.line_chart`/`st.bar_chart`, AppTest), psycopg2, pytest.

**Spec:** `docs/superpowers/specs/2026-09-18-ui-polish-design.md`.

## Global Constraints

- 브랜치 `feature/phase2c` (2B-2 브랜치 위). 커밋 메시지 끝에 빈 줄 + `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` (임시 파일 + `git commit -F`).
- 테스트는 저장소 루트에서 `python -m pytest -q`; 통합은 `DB_HOST=localhost python -m pytest -m integration <파일> -q -p no:cacheprovider`(`ragdb_test` 만, `ragdb` 에 `--rebuild`/DELETE 금지).
- AppTest 는 `app/tests/test_ui_apptest.py` 의 `app` 픽스처(`fake_index`)를 재사용한다. 그 가짜는 `rag.hybrid_search/rerank_candidates/answer_stream`, `qlog.log_question/set_feedback`, `db.get_conn/migrate` 를 패치하고 `calls` 목록에 호출을 기록한다. `chat_page` 는 모듈 속성으로 호출한다(`rag.xxx(...)`, `qlog.xxx(...)`).
- 답변 본문(LLM 출력)은 절대 `unsafe_allow_html=True` 로 그리지 않는다. 출처 카드의 값은 코퍼스 값(서비스·문서명·섹션·URL)만.
- 예시 질문 4개(스펙 3-5): `DNS Plus에서 레코드 세트를 생성하는 방법`, `SMS 발신 번호를 등록하는 절차`, `인스턴스를 생성하는 방법`, `Cloud Monitoring에서 대시보드를 생성하는 방법`. 힌트 문구: `서비스 이름을 함께 쓰면 더 정확합니다 (예: VPC, Object Storage)`.
- 인용 지시 문구(두 프롬프트 공통): `근거로 삼은 문서의 번호를 그 문장이나 단계 끝에 [1] 처럼 적어라. 문서 블록의 [문서 N] 번호와 같은 번호를 쓰고, 여러 문서면 [1][3] 처럼 이어 적어라.`
- 대화 목록은 세션 안에서만(최대 20개, 제목은 첫 질문 앞 24자), `questions.session_id` 는 브라우저 세션 단위 유지.
- 파일 UTF-8, 한국어 주석 톤 유지.

---

## 파일 구조

| 파일 | 책임 |
|---|---|
| `app/rag.py` (수정) | `_SYSTEM_COMMON` 에 인용 지시 |
| `app/chat_page.py` (수정) | 출처 카드, 진행 칩, 크게 보기, 다시 생성, 첫 화면, 대화 목록 |
| `app/conversations.py` (신규) | 세션 안 대화 목록 상태 조작(순수 함수 + session_state 어댑터) |
| `app/styles.py` (수정) | `.nhn-cite-card`, `.nhn-hint`, `.nhn-conv-title` |
| `app/admin_stats.py` (수정) | `daily`, `search`, `recent_down` 에 answer 전문·sources 추가 |
| `app/admin_page.py` (수정) | 차트, 👎 expander, 검색 |
| 테스트 | `app/tests/test_search_units.py`(프롬프트), `test_conversations.py`(신규), `test_ui_apptest.py`(추가), `test_admin_stats_db.py`(추가) |

---

### Task 1: 인용 지시 + 번호 매긴 출처 카드

**Files:**
- Modify: `app/rag.py` (`_SYSTEM_COMMON`)
- Modify: `app/chat_page.py` (`render_sources`)
- Modify: `app/styles.py`
- Test: `app/tests/test_search_units.py`, `app/tests/test_ui_apptest.py`

**Interfaces:**
- Produces: `chat_page.source_card_html(i: int, cand) -> str` (순수, 테스트 가능), `render_sources(cands)` 가 expander 없이 카드 목록을 그림.

- [ ] **Step 1: 실패하는 테스트**

`app/tests/test_search_units.py` 끝에:

```python
def test_both_prompts_ask_for_citations():
    for p in (rag.SYSTEM_PROMPT, rag.CONSOLE_SYSTEM_PROMPT):
        assert "[1] 처럼 적어라" in p and "[1][3]" in p
```

`app/tests/test_ui_apptest.py` 끝에:

```python
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
```

- [ ] **Step 2: 실패 확인** — `python -m pytest app/tests/test_search_units.py app/tests/test_ui_apptest.py -q` → 인용 문구 없음, `source_card_html` 없음.

- [ ] **Step 3: 구현**

`app/rag.py` `_SYSTEM_COMMON` 끝에 문장 추가:

```python
    "근거로 삼은 문서의 번호를 그 문장이나 단계 끝에 [1] 처럼 적어라. "
    "문서 블록의 [문서 N] 번호와 같은 번호를 쓰고, 여러 문서면 [1][3] 처럼 이어 적어라. "
```

`app/chat_page.py` — `render_sources` 교체:

```python
def source_card_html(i: int, c) -> str:
    """출처 카드 한 줄. 값은 전부 코퍼스에서 온 것(서비스·문서명·섹션·URL)이라 HTML 로 그린다."""
    name = os.path.splitext(os.path.basename(c.source_path))[0]
    section = (c.section_path or "").replace(" > ", " › ")
    link = f' <a href="{c.source_url}" target="_blank">원문 ↗</a>' if c.source_url else ""
    return (
        f'<div class="nhn-cite-card"><span class="nhn-cite-no">[{i}]</span> '
        f'<b>{name}</b> <span class="nhn-service-tag">{c.service}</span> '
        f'<span class="nhn-section">› {section}</span>{link}</div>'
    )


def render_sources(cands):
    """답변 아래 항상 보이는 번호 카드. 번호는 프롬프트의 [문서 N] 과 같다 (cands 순서)."""
    if not cands:
        return
    st.markdown("".join(source_card_html(i, c) for i, c in enumerate(cands, 1)), unsafe_allow_html=True)
```

`app/styles.py` 의 `.nhn-section` 뒤에:

```css
.nhn-cite-card { font-size: 0.8rem; padding: 0.3rem 0.5rem; margin-top: 0.25rem; border-left: 3px solid var(--nhn-blue-200); background: var(--nhn-blue-100); border-radius: 0 var(--nhn-radius-8) var(--nhn-radius-8) 0; }
.nhn-cite-no { color: var(--nhn-blue-800); font-weight: 700; margin-right: 0.2rem; }
.nhn-cite-card a { color: var(--nhn-blue-800); text-decoration: none; margin-left: 0.3rem; }
.nhn-cite-card a:hover { text-decoration: underline; }
```

(변수 이름은 `styles.py` 상단 `:root` 에 있는 것을 그대로 쓴다. 없으면 가장 가까운 기존 변수로 바꾼다.)

- [ ] **Step 4: 통과 확인** — 위 두 파일 + `python -m pytest -q` 전체.

- [ ] **Step 5: 커밋**

```bash
git add app/rag.py app/chat_page.py app/styles.py app/tests/test_search_units.py app/tests/test_ui_apptest.py
git commit -m "feat(ui): 인용 번호 지시와 번호 매긴 출처 카드

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: 진행 표시 칩과 짧은 상태 라벨

**Files:**
- Modify: `app/chat_page.py` (`answer_question`)
- Test: `app/tests/test_ui_apptest.py`

**Interfaces:**
- Produces: `chat_page.candidate_chip(c) -> str` (`서비스 · 문서명 › 섹션`), `answer_question` 이 status 안에 후보 칩을 그림.

- [ ] **Step 1: 실패하는 테스트**

```python
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
```

- [ ] **Step 2: 실패 확인** — `candidate_chip` 없음.

- [ ] **Step 3: 구현** — `app/chat_page.py`

```python
def candidate_chip(c) -> str:
    name = os.path.splitext(os.path.basename(c.source_path))[0]
    section = (c.section_path or "").replace(" > ", " › ")
    return f"{c.service} · {name}" + (f" › {section}" if section else "")


def render_progress_chips(slot, cands, limit=5):
    """status 안의 자리(slot)에 후보 문서를 한 줄씩 그린다. 리랭킹 뒤 같은 자리를 다시 그린다."""
    slot.markdown(
        "".join(f'<div class="nhn-progress-chip">{candidate_chip(c)}</div>' for c in cands[:limit]),
        unsafe_allow_html=True,
    )
```

`answer_question` 의 status 블록을 이렇게 바꾼다:

```python
            with st.status("검색 중…", expanded=False) as status:
                ... (search_q / intent / service 계산은 그대로)
                status.update(label=f"검색 중 · {INTENT_LABEL.get(intent, intent)} · {service or '서비스 미상'}")
                found = rag.hybrid_search(search_q, intent=intent, service=service, top_k=CANDIDATES)
                chips = st.empty()
                render_progress_chips(chips, found)
                status.update(label=f"관련도 평가 중 ({len(found)}건)")
                cands, grounded = rag.rerank_candidates(search_q, found, top_k=top_k)
                render_progress_chips(chips, cands)
                status.update(label=f"답변 작성 중 · 검색 {time.time() - t0:.1f}초", state="complete")
```

CSS(`styles.py`): `.nhn-progress-chip { font-size: 0.75rem; color: var(--nhn-gray-700); padding: 0.1rem 0; }`.

- [ ] **Step 4: 통과 확인** — `python -m pytest app/tests/test_ui_apptest.py -q`, 전체.

- [ ] **Step 5: 커밋** — `feat(ui): 진행 표시에 후보 문서 칩, 상태 라벨 단축` (+ 트레일러).

---

### Task 3: 스크린샷 크게 보기 다이얼로그

**Files:**
- Modify: `app/chat_page.py` (`render_answer`, 세션 카운터)
- Test: `app/tests/test_ui_apptest.py`

**Interfaces:**
- Produces: `chat_page.zoom_key(question_id, n, fallback_seq) -> str`, `@st.dialog` 함수 `show_screenshot(path, caption)`.

- [ ] **Step 1: 실패하는 테스트** — 기존 `test_markers_become_images` 와 같은 준비(tmp PNG, `DOCS_DIR` 패치)를 재사용해:

```python
def test_zoom_button_exists_and_opens_without_error(app, monkeypatch, tmp_path):
    at, _ = app
    import chat_page
    img_dir = tmp_path / "Network" / "VPC" / "images"
    img_dir.mkdir(parents=True)
    (img_dir / "a.png").write_bytes(PNG_1X1)   # 기존 테스트의 상수를 모듈 상단으로 올려 재사용
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
    assert chat_page.zoom_key(None, 2, 7) == "zoom_s7_2"
```

- [ ] **Step 2: 실패 확인**.

- [ ] **Step 3: 구현** — `app/chat_page.py`

```python
def zoom_key(question_id, n, fallback_seq):
    return f"zoom_q{question_id}_{n}" if question_id is not None else f"zoom_s{fallback_seq}_{n}"


@st.dialog("스크린샷", width="large")
def show_screenshot(path: str, caption: str):
    if not os.path.isfile(path):
        st.warning("스크린샷 파일을 찾을 수 없습니다")
        return
    st.image(path, caption=caption or None, width="stretch")
```

`render_answer(text, image_map, question_id=None, seq=0)` 로 시그니처를 넓히고, 이미지를 그린 뒤:

```python
        n = getattr(part, "number", None)  # ImageRef 에는 번호가 없으므로 아래처럼 enumerate 로 센다
```
→ 실제로는 `split_markers` 결과를 `enumerate` 하며 이미지마다 순번 `k`(1부터)를 매기고
`if st.button("크게 보기", key=zoom_key(question_id, k, seq)): show_screenshot(full, part.caption)`.
호출부: `render_assistant` 는 `render_answer(msg["content"], msg.get("image_map"), msg.get("question_id"), msg.get("seq", 0))`, 답변 직후 렌더는 `question_id` 가 아직 없으니(로그 전) `seq = st.session_state.setdefault("seq", 0) + 1` 로 세션 카운터를 올려 쓰고, 메시지 dict 에 `"seq": seq` 를 저장한다. 로그 뒤 다시 그릴 때는 `question_id` 키가 우선이라 첫 렌더와 기록 렌더의 키가 달라지는데, 첫 렌더 직후 rerun 되기 전에는 버튼을 누를 수 없으므로 문제 없다 — 다만 안전하게 **첫 렌더도 `seq` 키를 쓰고 기록 렌더도 `seq` 를 쓰도록 통일**한다(즉 `zoom_key` 는 `question_id` 가 있어도 `seq` 가 있으면 `seq` 우선). 테스트는 이 규칙에 맞춰 `zoom_key(42, 1, 0) == "zoom_q42_1"`(seq 0 = 없음), `zoom_key(42, 1, 7) == "zoom_s7_1"` 로 고친다.

- [ ] **Step 4: 통과 확인**, 전체.
- [ ] **Step 5: 커밋** — `feat(ui): 스크린샷 크게 보기 다이얼로그`.

---

### Task 4: 다시 생성 버튼과 첫 화면

**Files:**
- Modify: `app/chat_page.py` (`EXAMPLES`, 빈 화면, `feedback_buttons` 옆 버튼)
- Modify: `app/styles.py` (`.nhn-hint`)
- Test: `app/tests/test_ui_apptest.py`

- [ ] **Step 1: 실패하는 테스트**

```python
def test_examples_are_screenshot_rich_services():
    import chat_page
    assert chat_page.EXAMPLES == [
        "DNS Plus에서 레코드 세트를 생성하는 방법", "SMS 발신 번호를 등록하는 절차",
        "인스턴스를 생성하는 방법", "Cloud Monitoring에서 대시보드를 생성하는 방법",
    ]


def test_regenerate_reasks_same_question(app):
    at, calls = app
    at.run()
    at.chat_input[0].set_value("서브넷 만드는 법").run()
    searches = [c for c in calls if c[0] == "search"]
    assert len(searches) == 1
    regen = [b for b in at.button if b.label == "다시 생성"]
    assert regen
    regen[0].click().run()
    searches = [c for c in calls if c[0] == "search"]
    assert len(searches) == 2 and searches[1][1] == "서브넷 만드는 법"
    # 이전 답변은 남고 새 답변이 붙는다
    assert sum(1 for m in at.session_state["messages"] if m["role"] == "assistant") == 2


def test_empty_screen_shows_hint(app):
    at, _ = app
    at.run()
    assert any("서비스 이름을 함께 쓰면" in m.value for m in at.markdown)
```

- [ ] **Step 2: 실패 확인**.

- [ ] **Step 3: 구현**
- `EXAMPLES` 를 스펙의 4개로 교체.
- 빈 화면 `nhn-empty` 블록 뒤에 `st.markdown('<div class="nhn-hint">서비스 이름을 함께 쓰면 더 정확합니다 (예: VPC, Object Storage)</div>', unsafe_allow_html=True)`; CSS `.nhn-hint { text-align:center; font-size:0.8rem; color: var(--nhn-gray-700); margin-bottom: 1rem; }`.
- `feedback_buttons(question_id, question=None)` — 컬럼을 `[1, 1, 2, 6]` 로 늘리고 세 번째에 `if regen.button("다시 생성", key=f"regen_{key}")` (question_id 가 None 이면 `regen_s{seq}`): `st.session_state.pending = question; st.rerun()`. 호출부 두 곳 모두 `question` 을 넘긴다(기록 렌더는 직전 user 메시지 content — `render_assistant(msg, question)` 로 넘기고 page() 의 루프에서 직전 user 메시지를 기억해 전달).

- [ ] **Step 4: 통과**, 전체. **Step 5: 커밋** — `feat(ui): 다시 생성 버튼, 첫 화면 예시·힌트 교체`.

---

### Task 5: 세션 안 대화 목록

**Files:**
- Create: `app/conversations.py`
- Modify: `app/chat_page.py` (사이드바, messages 접근을 현재 대화로)
- Modify: `app/styles.py`
- Test: `app/tests/test_conversations.py`, `app/tests/test_ui_apptest.py`

**Interfaces:**
- Produces (`conversations.py`, session_state 를 인자로 받는 순수 함수):
  - `MAX_CONVERSATIONS = 20`, `TITLE_CHARS = 24`
  - `ensure(state) -> dict` — `state["conversations"]`(list)·`state["current"]` 를 만들고 현재 대화 dict 를 돌려준다. 대화 dict: `{"id": str, "title": str, "messages": list, "last_service": str | None}`.
  - `new(state) -> dict` — 새 대화를 맨 앞에 넣고 현재로. 20개 초과면 가장 오래된 것 제거.
  - `switch(state, conv_id) -> dict`
  - `title_for(question: str) -> str` — 앞 24자, 넘으면 `…`.
  - `set_title_if_empty(conv, question)`
  - `clear_current(state)` — 현재 대화의 messages 비움, 제목 유지.

- [ ] **Step 1: 실패하는 테스트** — `app/tests/test_conversations.py`

```python
import conversations as cv


def test_ensure_creates_first_conversation():
    s = {}
    c = cv.ensure(s)
    assert s["conversations"][0] is c and s["current"] == c["id"] and c["messages"] == [] and c["title"] == ""


def test_new_puts_conversation_first_and_caps():
    s = {}
    for i in range(cv.MAX_CONVERSATIONS + 3):
        c = cv.new(s)
        c["title"] = str(i)
    assert len(s["conversations"]) == cv.MAX_CONVERSATIONS
    assert s["conversations"][0]["title"] == str(cv.MAX_CONVERSATIONS + 2)
    assert s["current"] == s["conversations"][0]["id"]


def test_switch_and_clear():
    s = {}
    a = cv.new(s); a["messages"].append({"role": "user", "content": "a"})
    b = cv.new(s)
    assert cv.switch(s, a["id"]) is a and s["current"] == a["id"]
    cv.clear_current(s)
    assert a["messages"] == []


def test_title_for_truncates():
    assert cv.title_for("가" * 30) == "가" * 24 + "…"
    assert cv.title_for("짧은 질문") == "짧은 질문"
    c = {"title": ""}
    cv.set_title_if_empty(c, "첫 질문")
    cv.set_title_if_empty(c, "둘째")
    assert c["title"] == "첫 질문"
```

AppTest 추가:

```python
def test_new_conversation_and_switch(app):
    at, _ = app
    at.run()
    at.chat_input[0].set_value("서브넷 만드는 법").run()
    assert len(at.session_state["conversations"]) == 1
    assert at.session_state["conversations"][0]["title"].startswith("서브넷 만드는 법")
    new_btn = [b for b in at.sidebar.button if b.label == "새 대화"][0]
    new_btn.click().run()
    assert len(at.session_state["conversations"]) == 2
    assert at.session_state["conversations"][0]["messages"] == []
    # 이전 대화로 전환
    prev = [b for b in at.sidebar.button if b.label.startswith("서브넷 만드는 법")][0]
    prev.click().run()
    cur = next(c for c in at.session_state["conversations"] if c["id"] == at.session_state["current"])
    assert len(cur["messages"]) == 2
```

- [ ] **Step 2: 실패 확인**.

- [ ] **Step 3: 구현** — `app/conversations.py`

```python
"""세션 안 대화 목록 (스펙 4-1). 로그인이 없으므로 브라우저 세션 동안만 산다.
st.session_state 를 직접 import 하지 않고 dict 처럼 다루는 state 를 받는다 — 테스트가 쉽다."""
import uuid

MAX_CONVERSATIONS = 20
TITLE_CHARS = 24


def _make():
    return {"id": uuid.uuid4().hex, "title": "", "messages": [], "last_service": None}


def ensure(state):
    if "conversations" not in state or not state["conversations"]:
        state["conversations"] = [_make()]
        state["current"] = state["conversations"][0]["id"]
    if "current" not in state:
        state["current"] = state["conversations"][0]["id"]
    return current(state)


def current(state):
    for c in state["conversations"]:
        if c["id"] == state["current"]:
            return c
    state["current"] = state["conversations"][0]["id"]
    return state["conversations"][0]


def new(state):
    if "conversations" not in state:
        state["conversations"] = []
    c = _make()
    state["conversations"].insert(0, c)
    del state["conversations"][MAX_CONVERSATIONS:]
    state["current"] = c["id"]
    return c


def switch(state, conv_id):
    state["current"] = conv_id
    return current(state)


def title_for(question: str) -> str:
    q = " ".join(question.split())
    return q if len(q) <= TITLE_CHARS else q[:TITLE_CHARS] + "…"


def set_title_if_empty(conv, question):
    if not conv["title"]:
        conv["title"] = title_for(question)


def clear_current(state):
    current(state)["messages"] = []
```

`chat_page.py`: `st.session_state.messages` 를 쓰던 곳을 모두 현재 대화의 `messages` 로 바꾼다(`conv = cv.ensure(st.session_state)` 를 `page()` 초반에 두고 `conv["messages"]`; `answer_question` 도 `conv` 를 받아 append). `last_service` 도 `conv["last_service"]` 로. 사이드바 맨 위에:

```python
        if st.button("새 대화", width="stretch", key="conv_new"):
            cv.new(st.session_state); st.rerun()
        for c in st.session_state["conversations"]:
            label = c["title"] or "(빈 대화)"
            if st.button(label, key=f"conv_{c['id']}", width="stretch", type="primary" if c["id"] == st.session_state["current"] else "secondary"):
                cv.switch(st.session_state, c["id"]); st.rerun()
```
질문이 들어오면 `cv.set_title_if_empty(conv, question)`. `대화 초기화` 버튼은 `현재 대화 지우기` 로 이름을 바꾸고 `cv.clear_current` + `fb_`/`zoom_` 키 정리. 첫 화면 힌트 아래에 `대화 목록은 브라우저 탭을 닫으면 사라집니다` 한 줄 추가. 기존 AppTest 중 `at.session_state["messages"]` 를 읽는 테스트는 현재 대화의 messages 를 읽도록 고친다(헬퍼 `_messages(at)` 추가).

- [ ] **Step 4: 통과**, 전체. **Step 5: 커밋** — `feat(ui): 세션 안 대화 목록 (새 대화·전환·제목)`.

---

### Task 6: 관리자 시각화 — 일별 추이, 👎 답변 펼치기, 질문 검색

**Files:**
- Modify: `app/admin_stats.py` (`daily`, `search`, `recent_down` 컬럼 추가)
- Modify: `app/admin_page.py`
- Test: `app/tests/test_admin_stats_db.py`(통합), `app/tests/test_ui_apptest.py`

**Interfaces:**
- `admin_stats.daily(conn, since) -> list[tuple[date, int, float, int]]` — (일자 KST, 질문 수, 중앙값 초, 👎 수), 오래된 날부터.
- `admin_stats.search(conn, since, text, limit=50) -> list[tuple[datetime, str, str | None, bool | None, int | None]]` — (asked_at, question, service, grounded, feedback). `text` 가 비면 `[]`.
- `admin_stats.recent_down(conn, since, limit=20)` 반환 튜플을 `(asked_at, question, service, answer200, answer_full, sources)` 로 확장 (앞 4칸은 그대로라 기존 테스트 유지).

- [ ] **Step 1: 실패하는 통합 테스트** — `app/tests/test_admin_stats_db.py` 끝에(`seeded` 픽스처 재사용):

```python
def test_daily_groups_by_kst_date(seeded):
    import admin_stats as s
    rows = s.daily(seeded, None)
    assert len(rows) == 2                      # 오늘 4건 + 10일 전 1건
    today = rows[-1]
    assert today[1] == 4 and today[3] == 1     # 질문 4, 👎 1 (오늘 것만)
    assert isinstance(today[2], float)


def test_search_matches_question_text(seeded):
    import admin_stats as s
    assert s.search(seeded, None, "") == []
    rows = s.search(seeded, None, "q")
    assert len(rows) == 5 and all(len(r) == 5 for r in rows)
    assert s.search(seeded, None, "없는말") == []


def test_recent_down_carries_full_answer_and_sources(seeded):
    import admin_stats as s
    row = s.recent_down(seeded, None)[0]
    assert len(row) == 6 and len(row[3]) <= 200 and row[4].startswith("긴 답변") and row[5] == []
```

(`seeded` 의 `insert` 가 `sources="[]"` 를 넣으므로 `row[5] == []`.)

- [ ] **Step 2: 실패 확인** — `DB_HOST=localhost python -m pytest -m integration app/tests/test_admin_stats_db.py -q -p no:cacheprovider`.

- [ ] **Step 3: 구현** — `app/admin_stats.py`

```python
def daily(conn, since):
    rows = _rows(conn, f"""
        SELECT (asked_at AT TIME ZONE 'Asia/Seoul')::date AS d,
               count(*),
               percentile_cont(0.5) WITHIN GROUP (ORDER BY elapsed_ms),
               count(*) FILTER (WHERE feedback = -1)
          FROM questions WHERE {_SINCE}
         GROUP BY 1 ORDER BY 1""", {"since": since})
    return [(r[0], int(r[1]), round(float(r[2] or 0) / 1000, 1), int(r[3])) for r in rows]


def search(conn, since, text, limit=50):
    text = (text or "").strip()
    if not text:
        return []
    return _rows(conn, f"""
        SELECT asked_at, question, service, grounded, feedback
          FROM questions WHERE {_SINCE} AND question ILIKE %(pat)s
         ORDER BY asked_at DESC LIMIT %(limit)s""", {"since": since, "pat": f"%{text}%", "limit": limit})
```

`recent_down` 의 SELECT 에 `, coalesce(answer, ''), sources` 를 덧붙인다.

`app/admin_page.py` — 상단 지표 아래:

```python
    import pandas as pd
    rows = s.daily(conn, since)   # conn 이 열려 있는 try 블록 안에서 미리 읽어 둔다
    ...
    st.subheader("일별 추이")
    if not rows:
        st.info("기간 안에 질문이 없습니다")
    else:
        df = pd.DataFrame(rows, columns=["일자", "질문 수", "응답 중앙값(초)", "👎"]).set_index("일자")
        st.line_chart(df[["질문 수"]])
        st.line_chart(df[["응답 중앙값(초)"]])
        st.bar_chart(df[["👎"]])
```

👎 목록: 표 대신 행마다 `with st.expander(f"{asked_at:%m-%d %H:%M} · {question[:40]} · {service or '-'}"): st.markdown(answer_full); st.json(sources)`.
검색: `q = st.text_input("질문 검색", placeholder="질문에 포함된 단어")` → `s.search(conn, since, q)` 결과를 `st.dataframe`(컬럼 시각·질문·서비스·근거·피드백). 검색은 `conn` 이 닫힌 뒤 입력이 바뀌면 다시 열어야 하므로, 페이지 구조를 "입력 위젯 먼저 → 한 번의 try 로 모든 쿼리" 순서로 정리한다(`q` 를 위에서 읽고 try 안에서 `search` 호출).

AppTest 추가(기존 admin 테스트 스타일, `admin_auth.required_token` 을 `""` 로 패치):

```python
def test_admin_search_calls_search_and_shows_chart(monkeypatch):
    import admin_stats as s, admin_page, schema_ready, admin_auth
    from datetime import date, datetime, timezone
    calls = []
    monkeypatch.setattr(admin_auth, "required_token", lambda: "")
    monkeypatch.setattr(schema_ready, "ensure_schema", lambda: None)
    monkeypatch.setattr(admin_page, "get_conn", lambda: types.SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(s, "summary", lambda conn, since: {"questions": 1, "sessions": 1, "median_s": 1.0, "max_s": 1.0, "error_rate": 0.0, "ungrounded_rate": 0.0, "up": 0, "down": 1})
    monkeypatch.setattr(s, "by_service", lambda conn, since: [])
    monkeypatch.setattr(s, "daily", lambda conn, since: [(date.today(), 1, 1.0, 1)])
    monkeypatch.setattr(s, "recent_down", lambda conn, since, limit=20: [(datetime.now(timezone.utc), "q", "Network/VPC", "짧은", "긴 답변 전문", [])])
    monkeypatch.setattr(s, "recent_ungrounded", lambda conn, since, limit=20: [])
    monkeypatch.setattr(s, "recent_slow", lambda conn, since, limit=20, threshold_ms=30000: [])
    monkeypatch.setattr(s, "index_status", lambda conn: {"chunks": 1, "services": 1, "last_ingested_at": None})
    monkeypatch.setattr(s, "search", lambda conn, since, text, limit=50: calls.append(text) or [])
    at = AppTest.from_string("import admin_page\nadmin_page.page()\n", default_timeout=30)
    at.run()
    assert not at.exception
    assert any("긴 답변 전문" in m.value for m in at.markdown)
    at.text_input[0].set_value("서브넷").run()
    assert "서브넷" in calls
```

- [ ] **Step 4: 통과 확인** — 통합 3건, AppTest, 전체.
- [ ] **Step 5: 커밋** — `feat(admin): 일별 추이 차트, 👎 답변 펼치기, 질문 검색`.

---

### Task 7: README 갱신, 배포와 눈 확인 (Step 2 는 컨트롤러)

- [ ] **Step 1: README `## UI` 절 갱신** — 출처 카드·인용 번호, 크게 보기, 다시 생성, 대화 목록(세션 한정), 관리자 차트·검색을 문장으로. 예시 질문 목록 갱신. 커밋 `docs: 2C UI 고도화 안내`.
- [ ] **Step 2 (컨트롤러):** 이미지 `2c-<해시>` 빌드·푸시 → `set image` + CronJob 재-apply → 콘솔 질문 2건으로 카드·크게 보기·다시 생성·대화 전환·관리자 차트 확인(파드 exec + AppTest 로 대체 가능) → 보고.

---

## Self-review

- 스펙 3-1 → Task 2, 3-2 → Task 3, 3-3 → Task 1, 3-4·3-5 → Task 4, 4-1 → Task 5, 4-2 → Task 6, 5절 오류(파일 없음 경고 → Task 3 `show_screenshot`; 차트 0건 → Task 6), 6절 테스트 → 각 Task, 7절 범위 밖 준수.
- 자리표시자 없음. Task 3 의 키 규칙은 본문에서 최종 규칙(`seq` 우선)을 명시했고 테스트도 그 규칙으로 고치도록 적었다.
- 타입: `source_card_html(i, cand)`, `candidate_chip(c)`, `zoom_key(question_id, n, seq)`, `conversations.*` 시그니처를 테스트·구현이 같은 이름으로 씀. `recent_down` 6-튜플 확장은 기존 4칸 순서를 유지.
