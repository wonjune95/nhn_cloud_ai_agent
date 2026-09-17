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
