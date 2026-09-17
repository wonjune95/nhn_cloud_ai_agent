import os

import psycopg2

# 컨테이너 안에서는 서비스명 "db", 호스트(윈도우)에서 직접 돌릴 때는
# DB_HOST=localhost 로 덮어쓴다. 5432 는 compose 에서 이미 공개돼 있다.
DB_HOST = os.getenv("DB_HOST", "db")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "ragdb")
DB_USER = os.getenv("DB_USER", "devops")
DB_PASSWORD = os.getenv("DB_PASSWORD", "devops")


def get_conn():
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
    )


def _has_column(cur, table: str, column: str) -> bool:
    cur.execute(
        "SELECT 1 FROM information_schema.columns WHERE table_name = %s AND column_name = %s",
        (table, column),
    )
    return cur.fetchone() is not None


def _table_exists(cur, table: str) -> bool:
    cur.execute("SELECT 1 FROM information_schema.tables WHERE table_name = %s", (table,))
    return cur.fetchone() is not None


def _embedding_dim(cur) -> int | None:
    """documents.embedding 에 선언된 vector 차원. 알 수 없으면(컬럼 없음, -1/NULL) None."""
    cur.execute(
        "SELECT atttypmod FROM pg_attribute "
        "WHERE attrelid = 'documents'::regclass AND attname = 'embedding'"
    )
    row = cur.fetchone()
    if not row or row[0] is None or row[0] < 0:
        return None
    return row[0]


def embedding_dim(conn) -> int | None:
    """documents.embedding 의 선언 차원. 테이블이 없으면 None."""
    cur = conn.cursor()
    try:
        if not _table_exists(cur, "documents"):
            return None
        return _embedding_dim(cur)
    finally:
        cur.close()


HALFVEC_THRESHOLD = 2000   # pgvector 의 vector HNSW 상한. 넘으면 halfvec 표현식 인덱스를 쓴다.


def vector_order_by(dim: int) -> str:
    """벡터 검색 ORDER BY 식. 인덱스를 만든 표현식과 똑같아야 인덱스를 탄다."""
    if dim > HALFVEC_THRESHOLD:
        return f"(embedding::halfvec({dim})) <=> %s::halfvec({dim})"
    return "embedding <=> %s::vector"


def init_schema(conn, dim: int, rebuild: bool = False) -> None:
    """documents / questions 테이블과 인덱스를 만든다.

    rebuild=False 인데 구 스키마(content_hash 없음)가 남아 있으면 멈춘다 —
    그 위에 새 형식으로 INSERT 하면 실패하므로 명시적으로 --rebuild 를 요구한다.
    """
    cur = conn.cursor()
    cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    if rebuild:
        cur.execute("DROP TABLE IF EXISTS documents;")
    elif _table_exists(cur, "documents"):
        if not _has_column(cur, "documents", "content_hash"):
            raise RuntimeError("documents 테이블이 구 스키마입니다. python ingest.py --rebuild 로 실행하세요.")
        existing = _embedding_dim(cur)
        if existing is not None and existing != dim:
            raise RuntimeError(
                f"documents.embedding 차원이 {existing} 인데 현재 임베딩은 {dim} 입니다. "
                "python ingest.py --rebuild 로 실행하세요."
            )

    cur.execute(f"""
    CREATE TABLE IF NOT EXISTS documents (
        id           SERIAL PRIMARY KEY,
        content      TEXT NOT NULL,
        embedding    VECTOR({dim}),
        category     TEXT NOT NULL,
        service      TEXT NOT NULL,
        doc_type     TEXT NOT NULL,
        doc_title    TEXT NOT NULL,
        section_path TEXT NOT NULL,
        source_path  TEXT NOT NULL,
        source_url   TEXT,
        content_hash TEXT NOT NULL,
        images       JSONB NOT NULL DEFAULT '[]'
    );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS documents_service_doc_type ON documents (service, doc_type);")
    cur.execute("CREATE INDEX IF NOT EXISTS documents_source_path ON documents (source_path);")

    # vector 타입 HNSW 는 2000차원까지. 그 이상은 halfvec 표현식 인덱스(pgvector 0.7+).
    cur.execute("SAVEPOINT hnsw;")
    try:
        if dim > HALFVEC_THRESHOLD:
            cur.execute(
                "CREATE INDEX IF NOT EXISTS documents_embedding_hnsw "
                f"ON documents USING hnsw ((embedding::halfvec({dim})) halfvec_cosine_ops);"
            )
        else:
            cur.execute(
                "CREATE INDEX IF NOT EXISTS documents_embedding_hnsw "
                "ON documents USING hnsw (embedding vector_cosine_ops);"
            )
    except psycopg2.Error as e:
        cur.execute("ROLLBACK TO SAVEPOINT hnsw;")
        print(f"  [경고] HNSW 인덱스를 만들지 못했습니다 (pgvector 0.7 이상 필요): {str(e).strip()}")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS questions (
        id          SERIAL PRIMARY KEY,
        asked_at    TIMESTAMPTZ DEFAULT now(),
        question    TEXT NOT NULL,
        service     TEXT,
        intent      TEXT,
        grounded    BOOLEAN,
        elapsed_ms  INTEGER,
        sources     JSONB,
        error       TEXT,
        feedback    SMALLINT
    );
    """)

    conn.commit()
    cur.close()
