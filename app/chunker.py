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


def _table_lines(table) -> list[tuple[str, list]]:
    """표를 행 단위로 편다. 헤더가 있으면 '헤더: 값' 쌍으로 만들어 행이 스스로를 설명하게 한다.

    각 출력 줄과 함께 그 줄(즉 그 <tr>)에 들어 있는 <img> 태그 목록도 돌려준다. 나중에
    표가 여러 조각으로 쪼개질 때 각 이미지를 자기 행이 실제로 있는 조각에 붙이기 위함이다.
    """
    lines: list[tuple[str, list]] = []

    caption = table.find("caption")
    if caption:
        lines.append((f"[표] {caption.get_text(' ', strip=True)}", []))

    headers: list[str] = []
    for tr in table.find_all("tr"):
        cells = tr.find_all(["th", "td"])
        if not cells:
            continue

        values = [c.get_text(" ", strip=True) for c in cells]
        if not any(values):
            continue

        imgs_in_row = tr.find_all("img")

        if not headers and all(c.name == "th" for c in cells):
            headers = values
            lines.append((" | ".join(values), imgs_in_row))
            continue

        if headers and len(headers) == len(values):
            lines.append((" | ".join(f"{h}: {v}" for h, v in zip(headers, values) if v), imgs_in_row))
        else:
            lines.append((" | ".join(values), imgs_in_row))

    return lines


def table_to_text(table) -> str:
    """표를 행 단위로 편다. 헤더가 있으면 '헤더: 값' 쌍으로 만들어 행이 스스로를 설명하게 한다."""
    return "\n".join(line for line, _ in _table_lines(table))


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


def _split_long_block(
    text: str, images: list[Image], lines: list[int], max_chars: int
) -> list[tuple[str, list[Image]]]:
    """한 블록이 max_chars 를 넘고 여러 줄이면 줄 단위로 나눈다.

    표는 헤더 행, 코드는 '[코드]' 가 첫 줄이므로 첫 줄을 조각마다 반복해 각 조각이
    스스로를 설명하게 한다. 각 이미지는 `lines`(그 이미지가 속한 0-based 줄 번호)를 보고
    실제로 그 줄이 들어간 조각에 붙는다. 첫 줄(반복되는 헤더/코드 표시)에 달린 이미지는
    항상 첫 조각으로 간다.
    """
    text_lines = text.split("\n")
    if len(text) <= max_chars or len(text_lines) < 2:
        return [(text, images)]

    head, rest = text_lines[0], text_lines[1:]
    pieces: list[list[str]] = [[head]]
    length = len(head)
    line_to_piece: dict[int, int] = {0: 0}
    for offset, line in enumerate(rest, start=1):
        if len(pieces[-1]) > 1 and length + len(line) + 1 > max_chars:
            pieces.append([head])
            length = len(head)
        pieces[-1].append(line)
        length += len(line) + 1
        line_to_piece[offset] = len(pieces) - 1

    piece_texts = ["\n".join(piece) for piece in pieces]

    piece_images: list[list[Image]] = [[] for _ in pieces]
    for image, line_idx in zip(images, lines):
        piece_idx = 0 if line_idx == 0 else line_to_piece.get(line_idx, 0)
        piece_images[piece_idx].append(image)

    return [(piece_text, piece_images[i]) for i, piece_text in enumerate(piece_texts)]


def _build_chunks(
    doc_title: str,
    section_path: str,
    blocks: list[tuple[str, list[Image], list[int]]],
    max_chars: int,
) -> list[Chunk]:
    header = f"{doc_title} > {section_path}" if section_path else doc_title
    # 조각 하나가 헤더 줄과 함께 청크에 실려도 상한을 넘지 않도록, 분할 예산에서 헤더 줄
    # 길이를 미리 뺀다. 너무 짧아지지 않게 최소 200자는 보장한다.
    budget = max(max_chars - len(header) - 1, 200)

    expanded = [
        piece
        for text, images, lines in blocks
        for piece in _split_long_block(text, images, lines, budget)
    ]

    pieces: list[list[tuple[str, list[Image]]]] = []
    current: list[tuple[str, list[Image]]] = []
    length = len(header) + 1
    for text, images in expanded:
        # 마커 줄은 나중에 실제 인덱스로 다시 렌더링되지만, 두 자리 인덱스를 가정해
        # 크기를 넉넉히 어림잡는다(실제보다 작게 어림잡아 넘치는 일이 없도록).
        size = (len(text) + 1 if text else 0) + sum(len(_marker(99, im)) + 1 for im in images)
        if current and length + size > max_chars:
            pieces.append(current)
            current, length = [], len(header) + 1
        current.append((text, images))
        length += size
    if current:
        pieces.append(current)

    chunks = []
    for piece in pieces:
        content_lines = [header]
        images: list[Image] = []
        for text, block_images in piece:
            if text:
                content_lines.append(text)
            for image in block_images:
                images.append(image)
                content_lines.append(_marker(len(images), image))
        chunks.append(Chunk(content="\n".join(content_lines), section_path=section_path, images=images))
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
    sections: list[tuple[str, list[tuple[str, list[Image], list[int]]]]] = []
    blocks: list[tuple[str, list[Image], list[int]]] = []
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
            text = ""
            images = [_image(el, last_text, doc_rel_dir)]
            lines = [0]
        elif el.name == "table":
            table_lines = _table_lines(el)
            text = "\n".join(line for line, _ in table_lines)
            images = []
            lines = []
            for line_idx, (_line_text, imgs_in_row) in enumerate(table_lines):
                for img in imgs_in_row:
                    images.append(_image(img, _caption_for(img, el, text, last_text), doc_rel_dir))
                    lines.append(line_idx)
        else:
            text = _block_text(el)
            images = [_image(img, _caption_for(img, el, text, last_text), doc_rel_dir) for img in el.find_all("img")]
            lines = [0 for _ in images]
        if not text and not images:
            return
        if text:
            last_text = text
        blocks.append((text, images, lines))

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
