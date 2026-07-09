import os
from dotenv import load_dotenv

load_dotenv()

# data_pipeline/.env.example과 동일한 변수명 사용
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "tancheon_risk")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")

# 개별 변수를 조합해 최종 접속 문자열 생성
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}",
)

# 시민 제보 이미지 저장 경로
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "uploads/reports")