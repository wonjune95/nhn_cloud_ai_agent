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
