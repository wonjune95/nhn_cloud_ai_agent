"""질문 이해 — LLM 없이 규칙과 사전으로 의도와 서비스를 추정한다.

호출을 늘리면 요청 한도가 다시 문제가 되므로 여기서는 LLM 을 쓰지 않는다.
오판해도 검색 범위가 바뀌는 게 아니라 가중치만 달라지므로 비용이 낮다.
"""

import os

import yaml

APP_DIR = os.path.dirname(os.path.abspath(__file__))
GENERATED_ALIASES = os.path.join(APP_DIR, "services.generated.yaml")
MANUAL_ALIASES = os.path.join(APP_DIR, "services.yaml")

# 콘솔 절차를 묻는 신호. 하나라도 있으면 console.
CONSOLE_HINTS = (
    "어디서", "어떻게", "설정", "만들", "만드", "생성", "삭제", "메뉴", "버튼", "콘솔", "화면",
    "클릭", "추가", "등록", "연결", "변경", "절차", "방법", "하는 법", "하려면", "안 보여", "안보여",
)
# 절차 신호가 있어도 개념·API·요금 질문이면 general 로 되돌리는 신호.
GENERAL_OVERRIDES = ("차이", "api", "파라미터", "요금", "비용", "기준값", "유효기간", "릴리스", "지원 여부", "sla", "제한", "몇 개")


def detect_intent(question: str) -> str:
    q = question.lower()
    if any(h in q for h in GENERAL_OVERRIDES):
        return "general"
    return "console" if any(h in q for h in CONSOLE_HINTS) else "general"


def _read_yaml(path: str) -> dict:
    if not path or not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data if isinstance(data, dict) else {}


def load_aliases(generated_path: str | None = None, manual_path: str | None = None) -> dict[str, str]:
    """{별칭(소문자): '카테고리/서비스'}. 수동 사전이 자동 생성분을 덮어쓴다."""
    aliases: dict[str, str] = {}
    for path in (generated_path or GENERATED_ALIASES, manual_path or MANUAL_ALIASES):
        for service, names in _read_yaml(path).items():
            for name in names or []:
                key = " ".join(str(name).lower().split())
                if key:
                    aliases[key] = service
    return aliases


def detect_service(question: str, aliases: dict[str, str], fallback: str | None = None) -> str | None:
    q = " ".join(question.lower().split())
    hits = [alias for alias in aliases if alias in q]
    if not hits:
        return fallback
    return aliases[max(hits, key=len)]
