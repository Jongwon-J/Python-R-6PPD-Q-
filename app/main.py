from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.routers import traffic, reports, risk, documents
from app.config import UPLOAD_DIR
import os

app = FastAPI(title="EcoBridge-6PPDQ Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs(UPLOAD_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

app.include_router(traffic.router)
app.include_router(reports.router)
app.include_router(risk.router)
app.include_router(documents.router)

@app.get("/health")
def health_check():
    return {"status": "ok", "message": "서버가 살아있습니다"}

# 프론트엔드(대시보드/랜딩페이지)를 백엔드와 같은 서버에서 서빙.
# 배포 환경에서 별도 서버 없이 이 FastAPI 하나로 전체 서비스가 뜨게 하기 위함.
# API 라우터들을 먼저 등록한 뒤에 mount해야, "/"로 들어오는 정적 파일 요청이
# API 경로들과 충돌하지 않음.
FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
if os.path.isdir(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")