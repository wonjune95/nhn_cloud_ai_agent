"""nhn_cloud_docs/ 의 HTML 을 섹션 청크로 나눠 pgvector 에 적재한다.

    python ingest.py                 # 바뀐 문서만 (source_path + content_hash 비교)
    python ingest.py --rebuild       # 테이블을 지우고 전부 다시
    python ingest.py --limit 20      # 앞 20개 문서만 (시범)

문서 경로 규칙 '카테고리/서비스/문서명.html' 에서 category/service/doc_title 을,
문서명에서 doc_type 을 정한다. 이미지는 DB 에 넣지 않고 경로만 청크 메타에 둔다.
"""

import argparse
import hashlib
import json
import os
import sys
from typing import Iterator

from psycopg2.extras import Json

DOCS_DIR = os.getenv(
    "DOCS_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "nhn_cloud_docs"),
)
NO_SERVICE = "_"
BATCH_SIZE = 32


def doc_type_of(doc_title: str) -> str:
    upper = doc_title.upper()
    if "콘솔" in doc_title:
        return "console"
    if "API" in upper:
        return "api"
    if "개요" in doc_title:
        return "overview"
    return "other"


def split_source_path(rel_path: str) -> tuple[str, str, str]:
    """'카테고리/서비스/문서명.html' -> (category, service, doc_title)."""
    parts = rel_path.replace("\\", "/").strip("/").split("/")
    doc_title = os.path.splitext(parts[-1])[0]
    category = parts[0]
    service = parts[1] if len(parts) >= 3 else NO_SERVICE
    return category, service, doc_title


def iter_documents(docs_dir: str) -> Iterator[str]:
    for root, _, files in os.walk(docs_dir):
        for name in sorted(files):
            if name.endswith(".html"):
                rel = os.path.relpath(os.path.join(root, name), docs_dir)
                yield rel.replace("\\", "/")


def load_manifest_urls(docs_dir: str) -> dict[str, str]:
    path = os.path.join(docs_dir, "manifest.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return {e["path"]: e["url"] for e in json.load(f).values() if e.get("path")}


def file_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def existing_hash(cur, source_path: str) -> str | None:
    cur.execute("SELECT content_hash FROM documents WHERE source_path = %s LIMIT 1", (source_path,))
    row = cur.fetchone()
    return row[0] if row else None


def ingest_document(conn, docs_dir: str, rel_path: str, url: str | None) -> int:
    from chunker import chunk_html
    from llm import embed

    with open(os.path.join(docs_dir, rel_path), encoding="utf-8") as f:
        html = f.read()

    category, service, doc_title = split_source_path(rel_path)
    doc_rel_dir = os.path.dirname(rel_path)
    chunks = chunk_html(html, doc_title, doc_rel_dir)
    digest = file_hash(html)

    cur = conn.cursor()
    cur.execute("DELETE FROM documents WHERE source_path = %s", (rel_path,))

    for start in range(0, len(chunks), BATCH_SIZE):
        batch = chunks[start:start + BATCH_SIZE]
        vectors = embed([c.content for c in batch], input_type="passage")
        for chunk, vector in zip(batch, vectors):
            cur.execute(
                """INSERT INTO documents
                   (content, embedding, category, service, doc_type, doc_title,
                    section_path, source_path, source_url, content_hash, images)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (chunk.content, vector, category, service, doc_type_of(doc_title), doc_title,
                 chunk.section_path, rel_path, url, digest,
                 Json([{"path": i.path, "caption": i.caption, "alt": i.alt} for i in chunk.images])),
            )

    conn.commit()   # 문서 단위 커밋: 중간에 끊겨도 앞 문서는 남는다
    cur.close()
    return len(chunks)


def run(argv=None) -> int:
    from db import get_conn, init_schema
    from llm import EMBEDDING_MODEL_NAME, embed_one

    args = parse_args(argv)
    docs_dir = os.path.abspath(args.docs_dir)
    if not os.path.isdir(docs_dir):
        print(f"문서 폴더가 없습니다: {docs_dir}")
        return 1

    urls = load_manifest_urls(docs_dir)
    conn = get_conn()

    dim = len(embed_one("test"))
    print(f"임베딩 모델: {EMBEDDING_MODEL_NAME} (dim={dim}) / 문서 폴더: {docs_dir}")
    init_schema(conn, dim, rebuild=args.rebuild)

    done = skipped = 0
    total_chunks = 0
    failed: list[tuple[str, str]] = []
    cur = conn.cursor()

    for n, rel in enumerate(iter_documents(docs_dir), 1):
        if args.limit and n > args.limit:
            break

        with open(os.path.join(docs_dir, rel), encoding="utf-8") as f:
            digest = file_hash(f.read())
        if not args.rebuild and existing_hash(cur, rel) == digest:
            skipped += 1
            continue

        try:
            count = ingest_document(conn, docs_dir, rel, urls.get(rel))
        except Exception as e:
            conn.rollback()
            failed.append((rel, f"{type(e).__name__}: {e}"))
            print(f"  실패: {rel} — {e}")
            continue

        done += 1
        total_chunks += count
        print(f"[{n}] {rel} → {count} chunks")

    cur.close()
    conn.close()

    print(f"완료: 문서 {done}개 적재, {skipped}개 건너뜀, {len(failed)}개 실패 (청크 {total_chunks}개)")
    for rel, err in failed:
        print(f"  - {rel}: {err}")
    return 1 if failed else 0


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--docs-dir", default=DOCS_DIR)
    p.add_argument("--rebuild", action="store_true", help="documents 테이블을 지우고 전부 다시 적재")
    p.add_argument("--limit", type=int, default=0, help="앞 N개 문서만 (시범용)")
    return p.parse_args(argv)


if __name__ == "__main__":
    sys.exit(run())
