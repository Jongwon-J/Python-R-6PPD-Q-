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