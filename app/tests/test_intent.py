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
