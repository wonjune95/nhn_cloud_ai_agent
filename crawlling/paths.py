"""브레드크럼에서 저장 경로를 만든다.

docs.nhncloud.com 페이지 본문의 첫 <h2>는 "Compute > Virtual Desktop > 콘솔 사용 가이드"
형태의 브레드크럼이다. 메뉴 링크 이름만으로 파일명을 정하면 같은 카테고리의 여러
서비스가 서로 덮어쓰므로, 이 브레드크럼을 경로의 원천으로 쓴다.
"""

import re

from bs4 import BeautifulSoup

BREADCRUMB_SEP = ">"
NO_SERVICE = "_"
_FORBIDDEN = re.compile(r'[\\/*?:"<>|]')


def clean_name(text: str) -> str:
    """폴더·파일명으로 쓸 수 없는 문자를 _ 로 바꾼다."""
    return _FORBIDDEN.sub("_", text.strip())


def parse_breadcrumb(text: str) -> list[str]:
    parts = [p.strip() for p in text.split(BREADCRUMB_SEP)]
    return [p for p in parts if p]


def doc_path(parts: list[str]) -> str:
    """브레드크럼 조각 -> '카테고리/서비스/문서명.html'.

    2단이면 서비스 자리에 NO_SERVICE, 4단 이상이면 가운데를 ' - ' 로 이어 서비스로 본다.
    """
    if len(parts) < 2:
        raise ValueError(f"브레드크럼이 2단 미만입니다: {parts}")

    category = clean_name(parts[0])
    doc = clean_name(parts[-1])
    service = " - ".join(clean_name(p) for p in parts[1:-1]) or NO_SERVICE
    return f"{category}/{service}/{doc}.html"


def extract_breadcrumb(html: str) -> list[str] | None:
    soup = BeautifulSoup(html, "html.parser")
    h2 = soup.find("h2")
    if h2 is None:
        return None

    text = h2.get_text(" ", strip=True)
    if BREADCRUMB_SEP not in text:
        return None

    return parse_breadcrumb(text)


def fallback_path(category: str, menu_name: str) -> str:
    """브레드크럼이 없는 페이지는 메뉴 이름으로 저장한다."""
    return f"{clean_name(category)}/{NO_SERVICE}/{clean_name(menu_name)}.html"
