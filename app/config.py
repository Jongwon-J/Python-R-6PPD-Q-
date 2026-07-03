import os
# PostgreSQL 스키마 완성되면 실제 정보로 교체 예정
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://user:password@localhost:5432/ecobridge_db"
)