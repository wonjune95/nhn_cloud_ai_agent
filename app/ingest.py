"""nhn_cloud_docs/ 의 HTML 을 섹션 청크로 나눠 pgvector 에 적재한다.

    python ingest.py                 # 바뀐 문서만 (source_path + content_hash 비교)
    python ingest.py --rebuild       # 테이블을 지우고 전부 다시
    python ingest.py --limit 20      # 앞 20개 문서만 (시범)

문서 경로 규칙 '카테고리/서비스/문서명.html' 에서 category/service/doc_title 을,
문서명에서 doc_type 을 정한다. 이미지는 DB 에 넣지 않고 경로만 청크 메타에 둔다.
"""

import os

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
