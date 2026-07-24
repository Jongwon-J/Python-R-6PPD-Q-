from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import traffic, reports, risk, subscriptions
from app.routers import traffic, reports, risk, subscriptions, documents

app = FastAPI(title="EcoBridge-6PPDQ Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(traffic.router)
app.include_router(reports.router)
app.include_router(risk.router)
app.include_router(subscriptions.router)
app.include_router(documents.router)

@app.get("/health")
def health_check():
    return {"status": "ok", "message": "서버가 살아있습니다"}