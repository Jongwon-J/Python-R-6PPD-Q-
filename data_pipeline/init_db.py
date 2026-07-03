"""
init_db.py - 설계도를 실제로 실행하는 스크립트: schema.sql을 실행하여 PostgreSQL에 초기 테이블을 생성합니다.

사용법:
    python init_db.py

"""

import os
import logging

import psycopg2
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("init_db")

DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "localhost"),
    "port": os.environ.get("DB_PORT", "5432"),
    "dbname": os.environ["DB_NAME"],
    "user": os.environ["DB_USER"],
    "password": os.environ["DB_PASSWORD"],
}

SCHEMA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")


def main():
    with open(SCHEMA_FILE, "r", encoding="utf-8") as f:
        ddl = f.read()

    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn, conn.cursor() as cur:
            cur.execute(ddl)
        logger.info(f"스키마 적용 완료: {DB_CONFIG['dbname']}@{DB_CONFIG['host']}:{DB_CONFIG['port']}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
