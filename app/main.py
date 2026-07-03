from fastapi import FastAPI
from app.routers import traffic

app = FastAPI(title="EcoBridge-6PPDQ Backend")

app.include_router(traffic.router)

@app.get("/health")
def health_check():
    return {"status": "ok", "message": "서버가 살아있습니다"}