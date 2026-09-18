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
