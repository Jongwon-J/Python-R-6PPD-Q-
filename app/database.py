from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from app.config import DATABASE_URL

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """요청마다 새 DB 세션을 열고, 끝나면 자동으로 닫아주는 함수"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()