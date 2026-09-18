"""검색 인계(rerank_candidates / parse_rerank / build_prompt) 단위 테스트.

DB 도 LLM 도 쓰지 않는다: rag.chat 을 가짜로 바꾸고 bm25_meta 를 직접 채운다.
"""

import rag
from rag import Candidate


def cand(name, *, service="Network/VPC", section="서브넷 생성", doc_type="console"):
    return Candidate(
        content=f"{name} 본문",
        source_path=f"{service}/{name}.html",
        service=service,
        doc_type=doc_type,
        score=0.0,
        section_path=section,
        source_url=f"https://docs.nhncloud.com/ko/{name}/",
        images=[{"path": f"{service}/images/{name}.png", "caption": "캡션", "alt": "", "missing": False}],
    )


def fake_chat(scores, grounded):
    def _chat(prompt, **kwargs):
        return f"점수: {list(scores)}\n근거: {list(grounded)}"
    return _chat


# ---------------------------------------------------------------- Candidate 필드

def test_candidate_carries_chunk_metadata():
    c = cand("a")
    assert c.section_path == "서브넷 생성"
    assert c.source_url == "https://docs.nhncloud.com/ko/a/"
    assert c.images[0]["missing"] is False


def test_candidate_metadata_fields_are_optional_with_safe_defaults():
    c = Candidate(content="x", source_path="p", service="s", doc_type="other", score=0.0)
    assert c.section_path == ""
    assert c.source_url is None
    assert c.images == []
    # 기본 images 는 인스턴스마다 따로여야 한다 (가변 기본값 공유 금지).
    c.images.append(1)
    assert Candidate(content="y", source_path="p", service="s", doc_type="other", score=0.0).images == []


# ---------------------------------------------------------------- rerank_candidates

def test_rerank_candidates_orders_by_score_and_keeps_metadata(monkeypatch):
    monkeypatch.setattr(rag, "chat", fake_chat([2, 9, 5], [0, 1, 0]))
    cands = [cand("a"), cand("b", service="Storage/Object Storage"), cand("c")]

    top, grounded = rag.rerank_candidates("질문", cands, top_k=2)

    assert [c.content for c in top] == ["b 본문", "c 본문"]
    assert grounded is True
    assert top[0].service == "Storage/Object Storage"
    assert top[0].source_url == "https://docs.nhncloud.com/ko/b/"
    assert top[0].images[0]["path"] == "Storage/Object Storage/images/b.png"


def test_rerank_candidates_grounded_false_when_no_top_doc_is_grounded(monkeypatch):
    monkeypatch.setattr(rag, "chat", fake_chat([9, 8, 1], [0, 0, 1]))
    top, grounded = rag.rerank_candidates("질문", [cand("a"), cand("b"), cand("c")], top_k=2)
    assert [c.content for c in top] == ["a 본문", "b 본문"]
    assert grounded is False


def test_rerank_candidates_grounded_none_when_chat_raises(monkeypatch):
    def boom(prompt, **kwargs):
        raise RuntimeError("503")

    monkeypatch.setattr(rag, "chat", boom)
    cands = [cand("a"), cand("b"), cand("c")]
    top, grounded = rag.rerank_candidates("질문", cands, top_k=2)

    assert grounded is None
    assert [c.content for c in top] == ["a 본문", "b 본문"]   # 검색 순서 그대로


def test_rerank_candidates_grounded_none_when_response_unparsable(monkeypatch):
    monkeypatch.setattr(rag, "chat", lambda prompt, **kw: "잘 모르겠습니다")
    top, grounded = rag.rerank_candidates("질문", [cand("a")], top_k=5)
    assert grounded is None
    assert [c.content for c in top] == ["a 본문"]


def test_rerank_candidates_empty_input():
    assert rag.rerank_candidates("질문", [], top_k=5) == ([], False)


# ---------------------------------------------------------------- parse_rerank

def test_parse_rerank_prefers_labels_over_last_two_arrays():
    # 라벨 앞에 미끼 배열이 하나 더 있어도 라벨 뒤의 배열을 읽는다.
    text = "후보 번호: [0, 1, 2]\n점수: [10, 6, 0]\n근거: [1, 1, 0]"
    assert rag.parse_rerank(text, 3) == ([10.0, 6.0, 0.0], [True, True, False])

    # 라벨 뒤에 설명과 미끼 배열이 붙어도 마찬가지다 ('마지막 두 배열' 규칙이면 틀린다).
    trailing = "점수: [10, 6, 0]\n근거: [1, 1, 0]\n참고한 문서 번호: [0, 1]\n제외: [2, 2, 2]"
    assert rag.parse_rerank(trailing, 3) == ([10.0, 6.0, 0.0], [True, True, False])


def test_parse_rerank_falls_back_to_last_two_arrays_without_labels():
    assert rag.parse_rerank("[3, 1]\n[1, 0]", 2) == ([3.0, 1.0], [True, False])


def test_parse_rerank_label_form_with_json_quotes():
    assert rag.parse_rerank('{"점수": [8, 2], "근거": [1, 0]}', 2) == ([8.0, 2.0], [True, False])


def test_parse_rerank_wrong_length_returns_none():
    assert rag.parse_rerank("점수: [1, 2]\n근거: [1]", 2) is None


# ---------------------------------------------------------------- build_prompt

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


def test_system_prompt_warns_that_section_path_is_not_a_console_menu():
    assert "콘솔 메뉴 경로가 아니다" in rag.SYSTEM_PROMPT
    assert "본문에 명시된 것만" in rag.SYSTEM_PROMPT


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


def test_number_images_skips_remote_paths():
    """크롤러가 못 받아 원격 URL 을 그대로 남긴 이미지는 missing 과 똑같이 건너뛴다."""
    a = with_images("a", [
        {"path": "http://example.com/a.png", "caption": "원격1", "alt": "", "missing": False},
        {"path": "https://example.com/b.png", "caption": "원격2", "alt": "", "missing": False},
        {"path": "p/local.png", "caption": "로컬", "alt": "", "missing": False},
    ])
    image_map, per_cand = rag.number_images([a])
    assert list(image_map) == [1]
    assert image_map[1].path == "p/local.png"
    assert per_cand == [[1]]


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
    # 첫 줄은 문서 머리말의 '서비스: 카테고리/서비스' 에서 만든다.
    assert "콘솔 > 카테고리 > 서비스" in p
    assert "서비스: 카테고리/서비스" in p
    # '문서에 명시되지 않음' 으로 빠져나가는 길은 없앴다.
    assert "명시되지 않음" not in p
    assert "{{img:N}}" in p
    assert "주의" in p
    # 공통 근거 제한 문구는 두 프롬프트에 모두 있어야 한다.
    assert "제공된 문서에서 확인되지 않습니다" in p
    assert "제공된 문서에서 확인되지 않습니다" in rag.SYSTEM_PROMPT


# ---------------------------------------------------------------- 이웃 청크 이미지 차용

def chunk(text, *, doc="콘솔 사용 가이드", service="Network/VPC", section="서브넷 생성", images=None):
    """같은 문서(doc) 안의 서로 다른 청크. 본문만 다르고 source_path 는 같다."""
    c = cand(doc, service=service, section=section)
    c.content = f"{text} 본문"
    c.images = [] if images is None else images
    return c


def img(path, missing=False):
    return {"path": path, "caption": f"{path} 캡션", "alt": "", "missing": missing}


def test_enrich_images_borrows_from_siblings_in_same_doc_and_section(monkeypatch):
    target = chunk("절차", section="서브넷 생성 > 3단계")
    monkeypatch.setattr(rag, "bm25_meta", [
        # 같은 문서·같은 최상위 섹션 — missing 은 건너뛴다.
        chunk("옆1", images=[img("p/miss.png", missing=True), img("p/1.png")]),
        chunk("옆2", section="서브넷 생성 > 2단계", images=[img("p/2.png"), img("p/3.png"), img("p/4.png")]),
        # 다른 최상위 섹션 — 제외.
        chunk("다른섹션", section="VPC 생성", images=[img("p/other-section.png")]),
        # 다른 문서 — 제외.
        chunk("다른문서", doc="다른 가이드", section="서브넷 생성", images=[img("p/other-doc.png")]),
    ])

    out = rag.enrich_images([target], "console")

    assert [i["path"] for i in out[0].images] == ["p/1.png", "p/2.png", "p/3.png"]
    assert len(out[0].images) == rag.SIBLING_IMAGE_CAP
    # 나머지 필드는 그대로다.
    assert out[0].content == target.content and out[0].section_path == target.section_path


def test_enrich_images_leaves_candidate_with_images_alone(monkeypatch):
    monkeypatch.setattr(rag, "bm25_meta", [chunk("옆", images=[img("p/sib.png")])])
    c = cand("콘솔 사용 가이드")  # cand() 는 이미 이미지를 하나 들고 있다.

    out = rag.enrich_images([c], "console")

    assert out[0] is c
    assert [i["path"] for i in out[0].images] == ["Network/VPC/images/콘솔 사용 가이드.png"]


def test_enrich_images_is_noop_for_general_intent(monkeypatch):
    monkeypatch.setattr(rag, "bm25_meta", [chunk("옆", images=[img("p/1.png")])])
    cands = [chunk("절차")]

    assert rag.enrich_images(cands, "general") is cands
    assert cands[0].images == []


def test_enrich_images_does_not_mutate_the_original_candidate(monkeypatch):
    target = chunk("절차")
    monkeypatch.setattr(rag, "bm25_meta", [chunk("옆", section="서브넷 생성 > 2단계", images=[img("p/1.png")])])

    out = rag.enrich_images([target], "console")

    assert [i["path"] for i in out[0].images] == ["p/1.png"]
    assert target.images == []
    assert out[0] is not target


def test_enrich_images_keeps_candidate_without_any_sibling_image(monkeypatch):
    target = chunk("절차")
    monkeypatch.setattr(rag, "bm25_meta", [chunk("옆", doc="다른 가이드", images=[img("p/1.png")])])

    out = rag.enrich_images([target], "console")

    assert out[0] is target and out[0].images == []


def test_borrowed_images_are_numbered_like_any_other(monkeypatch):
    target = chunk("절차")
    monkeypatch.setattr(rag, "bm25_meta", [chunk("옆", section="서브넷 생성 > 2단계", images=[img("p/1.png")])])

    cands = rag.enrich_images([target], "console")
    prompt, image_map = rag.build_prompt("q", cands)

    assert image_map == {1: rag.ImageRef("p/1.png", "p/1.png 캡션")}
    assert "[그림 1] p/1.png 캡션" in prompt


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
