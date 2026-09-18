"""통합 테스트 공용 픽스처. 실데이터 DB(ragdb)를 건드리지 않도록 ragdb_test 를 쓴다."""
import pytest


@pytest.fixture(scope="session")
def test_db():
    import psycopg2
    import db

    admin = psycopg2.connect(host=db.DB_HOST, port=db.DB_PORT, database=db.DB_NAME,
                             user=db.DB_USER, password=db.DB_PASSWORD)
    admin.autocommit = True
    cur = admin.cursor()
    cur.execute("SELECT 1 FROM pg_database WHERE datname = 'ragdb_test'")
    if cur.fetchone() is None:
        cur.execute("CREATE DATABASE ragdb_test")
    cur.close()
    admin.close()

    original = db.DB_NAME
    db.DB_NAME = "ragdb_test"
    yield "ragdb_test"
    db.DB_NAME = original


@pytest.fixture
def conn(test_db):
    from db import get_conn
    c = get_conn()
    yield c
    c.close()
