"""HTML 문서를 섹션 단위 청크로 바꾼다.

NHN Cloud 콘솔 가이드는 h3/h4 하나가 작업 단계 묶음이고, 스크린샷은 대부분 설명 문단
바로 뒤의 빈 문단(<p><img/></p>)에 온다. 그래서 섹션을 청크 단위로 삼고, 이미지는 자기가
속한 블록의 텍스트를, 그 블록이 비어 있으면 직전 텍스트 블록을 캡션으로 잡는다.
li/blockquote 안에 중첩된 표·코드는 꺼내어 별도 블록으로 직렬화한다 (평문으로 뭉개지지 않게).
"""

from dataclasses import dataclass, field

from bs4 import BeautifulSoup

MAX_CHARS = 1500
CAPTION_CHARS = 60

HEADING_LEVELS = {"h2": 2, "h3": 3, "h4": 4}
BLOCK_TAGS = ["h2", "h3", "h4", "h5", "h6", "p", "li", "pre", "table", "blockquote", "img"]
# 다른 블록 안에 중첩돼 있어도 따로 직렬화해야 하는 태그
NESTED_BLOCKS = ["table", "pre"]


@dataclass
class Image:
    path: str
    caption: str
    alt: str = ""
    missing: bool = False


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


def _caption_for(img, el, text: str, last_text: str) -> str:
    """표 안 이미지는 감싸는 셀 텍스트, 그 외는 블록 텍스트, 블록이 비어 있으면 직전 텍스트."""
    if el.name == "table":
        cell = img.find_parent(["td", "th"])
        cell_text = cell.get_text(" ", strip=True) if cell is not None else ""
        if cell_text:
            return cell_text
    return text if text else last_text


def _image(img, caption: str, doc_rel_dir: str) -> Image:
    src = (img.get("src") or "").strip()
    if src.startswith("./"):
        path = f"{doc_rel_dir}/{src[2:]}"
    elif src.startswith(("http://", "https://")):
        path = src
    else:
        path = f"{doc_rel_dir}/{src}"
    return Image(
        path=path,
        caption=" ".join(caption.split()),
        alt=img.get("alt") or "",
        missing=(img.get("data-missing") == "true"),
    )


def _marker(index: int, image: Image) -> str:
    return f"[스크린샷 {index}: {image.caption[:CAPTION_CHARS]}]"


def _section_path(stack: dict[int, str]) -> str:
    return " > ".join(stack[level] for level in (2, 3, 4) if stack[level])


def _split_long_block(text: str, images: list[Image], max_chars: int) -> list[tuple[str, list[Image]]]:
    """한 블록이 max_chars 를 넘고 여러 줄이면 줄 단위로 나눈다.

    표는 헤더 행, 코드는 '[코드]' 가 첫 줄이므로 첫 줄을 조각마다 반복해 각 조각이
    스스로를 설명하게 한다. 이미지는 첫 조각에만 붙인다.
    """
    lines = text.split("\n")
    if len(text) <= max_chars or len(lines) < 2:
        return [(text, images)]

    head, rest = lines[0], lines[1:]
    pieces: list[str] = []
    current = [head]
    length = len(head)
    for line in rest:
        if len(current) > 1 and length + len(line) + 1 > max_chars:
            pieces.append("\n".join(current))
            current, length = [head], len(head)
        current.append(line)
        length += len(line) + 1
    pieces.append("\n".join(current))

    return [(piece, images if i == 0 else []) for i, piece in enumerate(pieces)]


def _build_chunks(doc_title: str, section_path: str, blocks: list[tuple[str, list[Image]]], max_chars: int) -> list[Chunk]:
    header = f"{doc_title} > {section_path}" if section_path else doc_title

    expanded = [piece for text, images in blocks for piece in _split_long_block(text, images, max_chars)]

    pieces: list[list[tuple[str, list[Image]]]] = []
    current: list[tuple[str, list[Image]]] = []
    length = len(header) + 1
    for text, images in expanded:
        size = (len(text) + 1 if text else 0) + sum(len(_marker(9, im)) + 1 for im in images)
        if current and length + size > max_chars:
            pieces.append(current)
            current, length = [], len(header) + 1
        current.append((text, images))
        length += size
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
                lines.append(_marker(len(images), image))
        chunks.append(Chunk(content="\n".join(lines), section_path=section_path, images=images))
    return chunks


def chunk_html(html: str, doc_title: str, doc_rel_dir: str, max_chars: int = MAX_CHARS,
               has_breadcrumb: bool | None = None) -> list[Chunk]:
    soup = BeautifulSoup(html, "html.parser")

    # 첫 h2 가 브레드크럼이면 메타데이터일 뿐이므로 본문에서 뺀다. manifest 가 알려주면 그 값을 믿는다.
    first_h2 = soup.find("h2")
    if first_h2 is not None:
        is_crumb = has_breadcrumb if has_breadcrumb is not None else (">" in first_h2.get_text(" ", strip=True))
        if is_crumb:
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

    def emit(el):
        nonlocal last_text
        if el.name == "img":
            text, images = "", [_image(el, last_text, doc_rel_dir)]
        else:
            text = _block_text(el)
            images = [_image(img, _caption_for(img, el, text, last_text), doc_rel_dir) for img in el.find_all("img")]
        if not text and not images:
            return
        if text:
            last_text = text
        blocks.append((text, images))

    # find_all 은 문서 순서라 상위 블록이 먼저 온다. 상위가 처리한 요소의 하위는 건너뛴다.
    for el in soup.find_all(BLOCK_TAGS):
        if id(el) in consumed or any(id(p) in consumed for p in el.parents):
            continue
        consumed.add(id(el))

        level = HEADING_LEVELS.get(el.name)
        if level:
            flush()
            stack[level] = el.get_text(" ", strip=True)
            for deeper in range(level + 1, 5):
                stack[deeper] = ""
            last_text = stack[level]
            continue

        # li/blockquote/p 안의 표·코드는 꺼내서 뒤에 따로 직렬화한다.
        nested = [] if el.name in NESTED_BLOCKS or el.name == "img" else el.find_all(NESTED_BLOCKS)
        for inner in nested:
            inner.extract()
            consumed.add(id(inner))

        emit(el)
        for inner in nested:
            emit(inner)

    flush()

    return [
        chunk
        for section_path, section_blocks in sections
        for chunk in _build_chunks(doc_title, section_path, section_blocks, max_chars)
    ]
