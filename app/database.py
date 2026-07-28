from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from app.config import DATABASE_URL

# 부하 테스트/운영 환경 대비: 워커 프로세스당 커넥션 풀을 명시적으로 지정.
# uvicorn --workers 4 기준으로 워커당 pool_size=10 + max_overflow=10 → 워커당 최대 20개,
# 전체 최대 80개 커넥션까지 열릴 수 있음. PostgreSQL 기본 max_connections(100)를 넘지 않게 설정.
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=10,
    pool_timeout=30,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """요청마다 새 DB 세션을 열고, 끝나면 자동으로 닫아주는 함수"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()