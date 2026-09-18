"""답변 본문의 {{img:N}} 마커를 텍스트/이미지 조각으로 나눈다 (스펙 3-4).

Streamlit 을 import 하지 않는다 — UI 와 평가 스크립트가 같이 쓰는 순수 함수다.
"""
import re
import sys

from rag import ImageRef

MARKER = re.compile(r"\{\{img:(\d+)\}\}")

# grounded == False 일 때 LLM 을 부르지 않고 그대로 보여 주는 문구 (스펙 3-3).
NOT_GROUNDED_MESSAGE = "제공된 문서에서 확인되지 않습니다."


def split_markers(text: str, image_map: dict[int, ImageRef]) -> list[tuple[str, str | ImageRef]]:
    """[("text", 문자열) | ("image", ImageRef)] 순서 목록. 순번표에 없는 번호는 지우고 stderr 에 남긴다."""
    parts: list[tuple[str, str | ImageRef]] = []
    pos = 0
    for m in MARKER.finditer(text):
        before = text[pos:m.start()]
        if before:
            parts.append(("text", before))
        n = int(m.group(1))
        ref = image_map.get(n)
        if ref is None:
            print(f"  [스크린샷] 순번표 밖 마커 {{{{img:{n}}}}} 제거 (그림 {len(image_map)}장)", file=sys.stderr)
        else:
            parts.append(("image", ref))
        pos = m.end()
    tail = text[pos:]
    if tail:
        parts.append(("text", tail))
    return parts


def valid_markers(text: str, image_map: dict[int, ImageRef]) -> list[int]:
    """본문에 나온 마커 번호 중 순번표에 있는 것만, 등장 순서대로."""
    return [int(n) for n in MARKER.findall(text) if int(n) in image_map]
