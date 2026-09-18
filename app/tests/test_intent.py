import pytest

from intent import CONSOLE_HINTS, detect_intent, detect_service, load_aliases


@pytest.mark.parametrize("q", [
    "VPC에 서브넷을 만드는 방법", "로드 밸런서는 어디서 설정해?", "인스턴스 생성 버튼이 안 보여",
    "플로팅 IP를 연결하려면 어떻게 해", "콘솔에서 키페어 등록", "NAT 게이트웨이 삭제하는 법",
    "보안 그룹 규칙 추가", "화면에서 DNS 레코드 변경", "오브젝트 스토리지 컨테이너 생성 절차", "알림 수신자 등록은 어떻게",
])
def test_console_intent(q):
    assert detect_intent(q) == "console"


@pytest.mark.parametrize("q", [
    "VPC와 서브넷의 차이가 뭐야", "SMS API 요청 파라미터 알려줘", "오브젝트 스토리지 요금 체계",
    "로드 밸런서 헬스체크 기준값", "리전이 몇 개야", "API 인증 토큰 유효기간", "릴리스 노트 최근 변경사항",
    "NAT 게이트웨이 대역폭 제한", "Terraform 프로바이더 지원 여부", "SLA 보장 수준",
])
def test_general_intent(q):
    assert detect_intent(q) == "general"


def test_console_hints_are_nonempty_tuple():
    assert isinstance(CONSOLE_HINTS, tuple) and "콘솔" in CONSOLE_HINTS


def test_load_aliases_merges_generated_and_manual(tmp_path):
    gen = tmp_path / "gen.yaml"
    gen.write_text("Network/VPC:\n- VPC\n- vpc\nStorage/Object Storage:\n- Object Storage\n", encoding="utf-8")
    man = tmp_path / "man.yaml"
    man.write_text("Network/Load Balancer:\n- LB\n- 로드밸런서\nNetwork/VPC:\n- 브이피씨\n", encoding="utf-8")
    aliases = load_aliases(str(gen), str(man))
    assert aliases["vpc"] == "Network/VPC"
    assert aliases["object storage"] == "Storage/Object Storage"
    assert aliases["lb"] == "Network/Load Balancer"
    assert aliases["브이피씨"] == "Network/VPC"


def test_load_aliases_tolerates_missing_files(tmp_path):
    assert load_aliases(str(tmp_path / "x.yaml"), str(tmp_path / "y.yaml")) == {}


ALIASES = {
    "storage": "Storage/_", "object storage": "Storage/Object Storage",
    "vpc": "Network/VPC", "lb": "Network/Load Balancer", "로드 밸런서": "Network/Load Balancer",
    "nat 게이트웨이": "Network/NAT Gateway",
}


def test_longest_alias_wins():
    assert detect_service("object storage에 파일 올리기", ALIASES) == "Storage/Object Storage"


def test_service_match_is_case_insensitive_and_korean():
    assert detect_service("Vpc 서브넷", ALIASES) == "Network/VPC"
    assert detect_service("로드 밸런서 생성", ALIASES) == "Network/Load Balancer"


def test_no_match_returns_fallback():
    assert detect_service("요금 문의", ALIASES) is None
    assert detect_service("그럼 삭제는?", ALIASES, fallback="Network/VPC") == "Network/VPC"


def test_ascii_alias_requires_word_boundary():
    aliases = {"nat": "Network/NAT Gateway", "acl": "Network/Network ACL", "vpc": "Network/VPC"}
    assert detect_service("NATO 동맹국 목록", aliases) is None
    assert detect_service("miracle 성능 개선", aliases) is None
    assert detect_service("NAT 게이트웨이 만들기", aliases) == "Network/NAT Gateway"
    assert detect_service("vpc에 서브넷 추가", aliases) == "Network/VPC"
    assert detect_service("my-vpc-1 설정", aliases) == "Network/VPC"


def test_korean_alias_matches_with_particles():
    aliases = {"서브넷": "Network/VPC"}
    assert detect_service("서브넷을 만들고 싶어", aliases) == "Network/VPC"


def test_load_aliases_skips_non_list_values(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("Network/VPC: VPC\nNetwork/LB:\n- LB\n", encoding="utf-8")
    aliases = load_aliases(str(bad), str(tmp_path / "none.yaml"))
    assert aliases == {"lb": "Network/LB"}


# ---- 실제 사전(services.generated.yaml + services.yaml) 으로 확인하는 회귀 테스트 ----
# 문서 제목이 '콘솔 사용 가이드' 류의 일반 명칭이라 제목 기반 별칭이 불가능하다.
# 한글 질문이 서비스로 이어지는지는 수동 사전(services.yaml)에 달려 있다.

@pytest.mark.parametrize("q,expected", [
    ("오브젝트 스토리지에 파일 업로드", "Storage/Object Storage"),
    ("전자세금계산서는 콘솔 어디서 확인해?", "Bill/eTax"),
    ("인스턴스를 생성하는 절차", "Compute/Instance"),
])
def test_default_aliases_resolve_korean_questions(q, expected):
    assert detect_service(q, load_aliases()) == expected


def test_manual_alias_keys_match_real_service_folders():
    """services.yaml 의 키는 '카테고리/서비스' 폴더명과 정확히 같아야 한다."""
    import os

    import yaml

    from intent import MANUAL_ALIASES

    docs_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "nhn_cloud_docs")
    if not os.path.isdir(docs_dir):
        pytest.skip("nhn_cloud_docs 코퍼스가 없습니다")

    with open(MANUAL_ALIASES, encoding="utf-8") as f:
        mapping = yaml.safe_load(f) or {}

    missing = [k for k in mapping if not os.path.isdir(os.path.join(docs_dir, *k.split("/")))]
    assert missing == []


@pytest.mark.parametrize("q", [
    "로그인 화면이 안 보여",      # '로그' 가 '로그인' 안에서 잡히면 안 된다
    "문자열 길이 제한",           # '문자' 가 '문자열' 안에서 잡히면 안 된다
    "이미지 업로드 방법",         # '이미지' 는 어느 서비스 질문에나 나온다
    "백업 설정은 어디서 해?",     # '백업' 도 마찬가지
])
def test_generic_korean_words_do_not_resolve_to_a_service(q):
    """한글 별칭은 부분 문자열 매칭이라 일반어를 별칭으로 두면 오탐이 난다."""
    assert detect_service(q, load_aliases()) is None


@pytest.mark.parametrize("q,expected", [
    ("문자 발송 실패", "Notification/SMS"),
    ("로그 검색에서 에러 찾기", "Data & Analytics/Log & Crash Search"),
    ("이미지 빌더로 이미지 만들기", "Compute/Image Builder"),
    ("웹 방화벽 룰 추가", "Security/WEB Firewall"),
])
def test_specific_multiword_aliases_still_resolve(q, expected):
    assert detect_service(q, load_aliases()) == expected
