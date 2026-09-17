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


def init_schema(conn, dim: int, rebuild: bool = False) -> None:
    """documents / questions 테이블과 인덱스를 만든다.

    rebuild=False 인데 구 스키마(content_hash 없음)가 남아 있으면 멈춘다 —
    그 위에 새 형식으로 INSERT 하면 실패하므로 명시적으로 --rebuild 를 요구한다.
    """
    cur = conn.cursor()
    cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    if rebuild:
        cur.execute("DROP TABLE IF EXISTS documents;")
    elif _table_exists(cur, "documents") and not _has_column(cur, "documents", "content_hash"):
        raise RuntimeError("documents 테이블이 구 스키마입니다. python ingest.py --rebuild 로 실행하세요.")

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

    # HNSW 는 pgvector 0.5 이상. 구버전이면 인덱스 없이 순차 스캔으로 동작한다.
    cur.execute("SAVEPOINT hnsw;")
    try:
        cur.execute(
            "CREATE INDEX IF NOT EXISTS documents_embedding_hnsw "
            "ON documents USING hnsw (embedding vector_cosine_ops);"
        )
    except psycopg2.Error as e:
        cur.execute("ROLLBACK TO SAVEPOINT hnsw;")
        print(f"  [경고] HNSW 인덱스를 만들지 못했습니다 (pgvector 버전 확인): {str(e).strip()}")

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
