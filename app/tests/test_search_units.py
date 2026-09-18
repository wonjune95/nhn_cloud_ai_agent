"""검색 인계(rerank_candidates / parse_rerank / build_prompt) 단위 테스트.

DB 도 LLM 도 쓰지 않는다: rag.chat 을 가짜로 바꾸고 doc_meta/bm25_meta 를 직접 채운다.
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


# ---------------------------------------------------------------- rerank (문자열 래퍼)

def test_rerank_wrapper_returns_strings(monkeypatch):
    monkeypatch.setattr(rag, "chat", fake_chat([1, 7], [1, 1]))
    monkeypatch.setattr(rag, "doc_meta", {
        "a 본문": ("Network/VPC/a.html", "Network/VPC", "console", "서브넷 생성"),
        "b 본문": ("Storage/Object Storage/b.html", "Storage/Object Storage", "other", "업로드"),
    })

    docs, grounded = rag.rerank("질문", ["a 본문", "b 본문"], top_k=2)

    assert docs == ["b 본문", "a 본문"]
    assert all(isinstance(d, str) for d in docs)
    assert grounded is True


def test_rerank_wrapper_handles_unknown_content(monkeypatch):
    monkeypatch.setattr(rag, "chat", fake_chat([5], [0]))
    monkeypatch.setattr(rag, "doc_meta", {})
    docs, grounded = rag.rerank("질문", ["처음 보는 본문"])
    assert docs == ["처음 보는 본문"]
    assert grounded is False


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
    prompt = rag.build_prompt("VPC 서브넷 만드는 법", [cand("콘솔 사용 가이드")])

    assert (
        "[문서 1] 서비스: Network/VPC · 문서: 콘솔 사용 가이드 · "
        "섹션: 서브넷 생성 · 출처: Network/VPC/콘솔 사용 가이드.html"
    ) in prompt
    assert "콘솔 사용 가이드 본문" in prompt
    assert "VPC 서브넷 만드는 법" in prompt
    # 옛 머리말 형식은 더 이상 쓰지 않는다.
    assert "(서비스:" not in prompt


def test_build_prompt_numbers_documents_from_one():
    prompt = rag.build_prompt("q", [cand("a"), cand("b")])
    assert "[문서 1]" in prompt and "[문서 2]" in prompt


def test_build_prompt_accepts_strings_via_doc_meta(monkeypatch):
    monkeypatch.setattr(rag, "doc_meta", {
        "a 본문": ("Network/VPC/콘솔 사용 가이드.html", "Network/VPC", "console", "서브넷 생성"),
    })
    prompt = rag.build_prompt("q", ["a 본문"])
    assert "문서: 콘솔 사용 가이드" in prompt
    assert "섹션: 서브넷 생성" in prompt


def test_build_prompt_includes_history():
    history = [{"role": "user", "content": "VPC 가 뭐야"}, {"role": "assistant", "content": "가상 네트워크다"}]
    prompt = rag.build_prompt("그럼 서브넷은?", [cand("a")], history)
    assert "이전 대화:" in prompt
    assert "사용자: VPC 가 뭐야" in prompt


def test_system_prompt_warns_that_section_path_is_not_a_console_menu():
    assert "콘솔 메뉴 경로가 아니다" in rag.SYSTEM_PROMPT
    assert "본문에 명시된 것만" in rag.SYSTEM_PROMPT


# ---------------------------------------------------------------- bm25 인덱스 기반 귀속

def test_bm25_hits_use_index_not_content_for_duplicate_chunks(monkeypatch):
    """같은 본문이 두 문서에 있어도 BM25 히트는 자기 인덱스의 메타를 쓴다."""
    dup = "같은 본문"
    first = Candidate(content=dup, source_path="Network/VPC/a.html", service="Network/VPC",
                      doc_type="console", score=0.0, section_path="A")
    second = Candidate(content=dup, source_path="Storage/NAS/b.html", service="Storage/NAS",
                       doc_type="other", score=0.0, section_path="B")

    monkeypatch.setattr(rag, "bm25_corpus", [dup, dup])
    monkeypatch.setattr(rag, "bm25_meta", [first, second])
    # 본문 키 사전은 먼저 온 문서만 담는다 — 그래서 인덱스 기반이어야 한다.
    monkeypatch.setattr(rag, "doc_meta", {dup: ("Network/VPC/a.html", "Network/VPC", "console", "A")})

    assert rag.bm25_meta[1].source_path == "Storage/NAS/b.html"
    assert rag._candidate(dup).source_path == "Network/VPC/a.html"
