"""HTML 문서를 섹션 단위 청크로 바꾼다.

NHN Cloud 콘솔 가이드는 h3/h4 하나가 작업 단계 묶음이고, 스크린샷은 대부분(92%)
설명 문단 바로 뒤에 온다. 그래서 섹션을 청크 단위로 삼고, 이미지는 자기가 속한
블록(문단·목록 항목·표 칸)에 묶어 캡션을 그 블록 텍스트로 잡는다.
"""

from dataclasses import dataclass, field

from bs4 import BeautifulSoup

MAX_CHARS = 1500
CAPTION_CHARS = 60

HEADING_LEVELS = {"h2": 2, "h3": 3, "h4": 4}
BLOCK_TAGS = ["h2", "h3", "h4", "h5", "h6", "p", "li", "pre", "table", "blockquote", "img"]


@dataclass
class Image:
    path: str
    caption: str
    alt: str = ""


@dataclass
class Chunk:
    content: str
    section_path: str
    images: list[Image] = field(default_factory=list)


def table_to_text(table) -> str:
    """표를 행 단위로 편다. 헤더가 있으면 '헤더: 값' 쌍으로 만들어 행이 스스로를 설명하게 한다."""
    lines = []

    caption = table.find("caption")
    if caption:
        lines.append(f"[표] {caption.get_text(' ', strip=True)}")

    headers: list[str] = []
    for tr in table.find_all("tr"):
        cells = tr.find_all(["th", "td"])
        if not cells:
            continue

        values = [c.get_text(" ", strip=True) for c in cells]
        if not any(values):
            continue

        if not headers and all(c.name == "th" for c in cells):
            headers = values
            lines.append(" | ".join(values))
            continue

        if headers and len(headers) == len(values):
            lines.append(" | ".join(f"{h}: {v}" for h, v in zip(headers, values) if v))
        else:
            lines.append(" | ".join(values))

    return "\n".join(lines)


def _block_text(el) -> str:
    if el.name == "table":
        return table_to_text(el)
    if el.name == "pre":
        return "[코드]\n" + el.get_text().strip()
    return el.get_text(" ", strip=True)


def _image(img, caption: str, doc_rel_dir: str) -> Image:
    src = (img.get("src") or "").strip()
    if src.startswith("./"):
        path = f"{doc_rel_dir}/{src[2:]}"
    elif src.startswith(("http://", "https://")):
        path = src
    else:
        path = f"{doc_rel_dir}/{src}"
    return Image(path=path, caption=caption, alt=img.get("alt") or "")


def _section_path(stack: dict[int, str]) -> str:
    return " > ".join(stack[level] for level in (2, 3, 4) if stack[level])


def _build_chunks(doc_title: str, section_path: str, blocks: list[tuple[str, list[Image]]], max_chars: int) -> list[Chunk]:
    header = f"{doc_title} > {section_path}" if section_path else doc_title

    pieces: list[list[tuple[str, list[Image]]]] = []
    current: list[tuple[str, list[Image]]] = []
    length = 0
    for text, images in blocks:
        if current and length + len(text) + 1 > max_chars:
            pieces.append(current)
            current, length = [], 0
        current.append((text, images))
        length += len(text) + 1
    if current:
        pieces.append(current)

    chunks = []
    for piece in pieces:
        lines = [header]
        images: list[Image] = []
        for text, block_images in piece:
            if text:
                lines.append(text)
            for image in block_images:
                images.append(image)
                lines.append(f"[스크린샷 {len(images)}: {image.caption[:CAPTION_CHARS]}]")
        chunks.append(Chunk(content="\n".join(lines), section_path=section_path, images=images))
    return chunks


def chunk_html(html: str, doc_title: str, doc_rel_dir: str, max_chars: int = MAX_CHARS) -> list[Chunk]:
    soup = BeautifulSoup(html, "html.parser")

    # 첫 h2 가 브레드크럼이면 메타데이터일 뿐이므로 본문에서 뺀다.
    first_h2 = soup.find("h2")
    if first_h2 is not None and ">" in first_h2.get_text(" ", strip=True):
        first_h2.decompose()

    stack = {2: "", 3: "", 4: ""}
    sections: list[tuple[str, list[tuple[str, list[Image]]]]] = []
    blocks: list[tuple[str, list[Image]]] = []
    consumed: set[int] = set()
    last_text = ""

    def flush():
        nonlocal blocks
        if blocks:
            sections.append((_section_path(stack), blocks))
        blocks = []

    # find_all 은 문서 순서라 상위 블록이 먼저 온다. 상위가 처리한 요소의 하위는 건너뛴다.
    for el in soup.find_all(BLOCK_TAGS):
        if any(id(p) in consumed for p in el.parents):
            continue
        consumed.add(id(el))

        level = HEADING_LEVELS.get(el.name)
        if level:
            flush()
            stack[level] = el.get_text(" ", strip=True)
            for deeper in range(level + 1, 5):
                stack[deeper] = ""
            continue

        if el.name == "img":
            text, images = "", [_image(el, last_text, doc_rel_dir)]
        else:
            text = _block_text(el)
            images = [_image(img, text, doc_rel_dir) for img in el.find_all("img")]

        if not text and not images:
            continue
        if text:
            last_text = text
        blocks.append((text, images))

    flush()

    return [
        chunk
        for section_path, section_blocks in sections
        for chunk in _build_chunks(doc_title, section_path, section_blocks, max_chars)
    ]
