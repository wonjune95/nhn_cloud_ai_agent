import os
from bs4 import BeautifulSoup
from db import get_conn
from llm import EMBEDDING_MODEL_NAME, embed, embed_one

DATA_DIR = "./data"

MAX_CHARS = 800
# NIM 임베딩은 배열 입력을 받는다. 청크를 묶어 보내 호출 횟수를 줄인다.
BATCH_SIZE = 32

# 본문을 이루는 블록 요소. 표(table)와 코드(pre)는 전용 직렬화를 거친다.
BLOCK_TAGS = ["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "pre", "table", "blockquote"]


def table_to_text(table):
    """표를 행 단위 텍스트로 편다.

    NHN Cloud API 가이드는 파라미터·응답 필드가 대부분 표에 들어 있다.
    셀을 그냥 이어 붙이면 800자 청킹에서 잘렸을 때 어느 열의 값인지 알 수 없으므로,
    헤더가 있으면 "헤더: 값" 쌍으로 만들어 행 하나가 스스로를 설명하게 한다.
    """
    lines = []

    caption = table.find("caption")
    if caption:
        lines.append(f"[표] {caption.get_text(' ', strip=True)}")

    headers = []

    for tr in table.find_all("tr"):
        cells = tr.find_all(["th", "td"])
        if not cells:
            continue

        values = [c.get_text(" ", strip=True) for c in cells]
        if not any(values):
            continue

        # 첫 머리글 행은 헤더로 기억해 둔다.
        if not headers and all(c.name == "th" for c in cells):
            headers = values
            lines.append(" | ".join(values))
            continue

        if headers and len(headers) == len(values):
            lines.append(" | ".join(f"{h}: {v}" for h, v in zip(headers, values) if v))
        else:
            lines.append(" | ".join(values))

    return "\n".join(lines)


def extract_text(html_path):
    with open(html_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f, "html.parser")

    texts = []
    consumed = set()

    # find_all 은 문서 순서대로 반환하므로 상위 블록이 항상 먼저 나온다.
    # 상위 블록이 이미 처리한 내용을 하위에서 다시 담지 않도록 조상을 확인한다.
    for el in soup.find_all(BLOCK_TAGS):
        if any(id(p) in consumed for p in el.parents):
            continue

        if el.name == "table":
            text = table_to_text(el)
        elif el.name == "pre":
            # 코드 예제는 들여쓰기가 의미를 가지므로 원문을 그대로 둔다.
            text = "[코드]\n" + el.get_text().strip()
        elif el.name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            text = "#" * int(el.name[1]) + " " + el.get_text(" ", strip=True)
        else:
            text = el.get_text(" ", strip=True)

        consumed.add(id(el))

        if text.strip():
            texts.append(text)

    # 🔥 이미지 설명 포함
    for img in soup.find_all("img"):
        alt = img.get("alt") or ""
        src = img.get("src") or ""
        texts.append(f"[이미지] {alt} {src}")

    return "\n".join(texts)

def split_text(text, chunk_size=800, overlap=150):
    chunks = []
    start = 0

    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        chunks.append(chunk)

        start += (chunk_size - overlap)

    return chunks


def embed_text(text):
    return embed_one(text, input_type="passage")

def embed_texts(texts):
    return embed(texts, input_type="passage")

def split_text_with_overlap(text, chunk_size=800, overlap=150):
    chunks = []
    start = 0

    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        chunks.append(chunk)

        start += (chunk_size - overlap)

    return chunks

def extract_with_images(html_path):
    from bs4 import BeautifulSoup

    with open(html_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f, "html.parser")

    texts = []

    for tag in soup.find_all(["p", "h1", "h2", "h3", "li"]):
        texts.append(tag.get_text(strip=True))

    # 🔥 이미지 설명 추가
    for img in soup.find_all("img"):
        alt = img.get("alt") or ""
        src = img.get("src") or ""

        if alt or src:
            texts.append(f"[이미지 설명] {alt} {src}")

    return "\n".join(texts)

def extract_service(path):
    parts = path.replace("\\", "/").split("/")
    return parts[2] if len(parts) > 2 else "unknown"

def init_db(cur):
    cur.execute("DROP TABLE IF EXISTS documents;")
    cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    # dimension 자동 추출 = nvidia/nemotron-3-embed-1b 기준 2048
    dim = len(embed_text("test"))
    print(f"임베딩 모델: {EMBEDDING_MODEL_NAME} (dim={dim})")

    cur.execute(f"""
    CREATE TABLE documents (
        id SERIAL PRIMARY KEY,
        content TEXT,
        embedding VECTOR({dim}),
        source TEXT,
        service TEXT
    );
    """)


def ingest():
    conn = get_conn()
    cur = conn.cursor()

    init_db(cur)

    total = 0
    skipped = 0

    # API 가이드는 엔드포인트마다 같은 공통 응답 표를 반복한다. 완전히 같은 청크를
    # 여러 벌 넣으면 검색 상위 K개를 동일 내용이 차지해버리므로 한 벌만 남긴다.
    seen = set()

    for root, _, files in os.walk(DATA_DIR):
        for file in files:
            if not file.endswith(".html"):
                continue

            path = os.path.join(root, file)

            text = extract_text(path)

            chunks = []
            for c in split_text(text):
                key = c.strip()
                if not key or key in seen:
                    skipped += 1
                    continue
                seen.add(key)
                chunks.append(c)

            if not chunks:
                continue

            print(f"{file} → {len(chunks)} chunks")

            service = extract_service(path)

            for i in range(0, len(chunks), BATCH_SIZE):
                batch = chunks[i:i + BATCH_SIZE]
                embeddings = embed_texts(batch)

                for chunk, emb in zip(batch, embeddings):
                    cur.execute(
                        "INSERT INTO documents (content, embedding, source, service) VALUES (%s, %s, %s, %s)",
                        (chunk, emb, path, service)
                    )

            total += len(chunks)
            # 파일 단위로 커밋해 중간에 끊겨도 앞부분이 남도록 한다.
            conn.commit()

    conn.commit()
    print(f"완료: 총 {total} chunks 적재 (중복 제거 {skipped}개)")

    cur.close()
    conn.close()


if __name__ == "__main__":
    ingest()
