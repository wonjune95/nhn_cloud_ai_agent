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
