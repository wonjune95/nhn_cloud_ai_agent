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
