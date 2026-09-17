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
    # 문서가 2개뿐이면 IDF 가 log(1)=0 이라 점수가 안 나온다. 무관 문서를 셋 둔다.
    docs = [
        "인스턴스 생성 버튼을 클릭합니다",
        "오브젝트 스토리지 컨테이너를 만듭니다",
        "로드 밸런서 리스너를 추가합니다",
        "요금은 시간 단위로 청구됩니다",
    ]
    bm25 = BM25Okapi([tokenize(d) for d in docs])
    scores = bm25.get_scores(tokenize("인스턴스를 생성하려면"))
    assert scores[0] > 0
    assert all(scores[0] > s for s in scores[1:])
