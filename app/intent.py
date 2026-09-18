"""질문 이해 — LLM 없이 규칙과 사전으로 의도와 서비스를 추정한다.

호출을 늘리면 요청 한도가 다시 문제가 되므로 여기서는 LLM 을 쓰지 않는다.
오판해도 검색 범위가 바뀌는 게 아니라 가중치만 달라지므로 비용이 낮다.
"""

import os
import re

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

_ASCII = re.compile(r"^[a-z0-9 ._-]+$")


def _alias_hits(q: str, aliases: dict[str, str]) -> list[str]:
    """Find matching aliases in question, with word boundaries for ASCII-only aliases.

    영문 약칭은 단어 경계로만 매칭한다 ("nat" 이 "nato" 안에서 잡히지 않게).
    """
    hits = []
    for alias in aliases:
        if _ASCII.match(alias):
            # ASCII-only aliases require word boundaries
            if re.search(r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])", q):
                hits.append(alias)
        elif alias in q:
            # Hangul aliases use substring matching (particles attach directly)
            hits.append(alias)
    return hits


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
            if not isinstance(names, list):
                continue
            for name in names or []:
                key = " ".join(str(name).lower().split())
                if key:
                    aliases[key] = service
    return aliases


def detect_service(question: str, aliases: dict[str, str], fallback: str | None = None) -> str | None:
    q = " ".join(question.lower().split())
    hits = _alias_hits(q, aliases)
    if not hits:
        return fallback
    return aliases[max(hits, key=len)]
