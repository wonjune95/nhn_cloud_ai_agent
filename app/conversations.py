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
    # 이미 빈 대화를 보고 있으면 그 대화를 또 만들지 않고 그대로 재사용한다 —
    # 안 그러면 '새 대화'를 누를 때마다 빈 대화만 쌓인다.
    if state["conversations"] and state.get("current") is not None:
        cur = current(state)
        if not cur["messages"]:
            return cur
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
