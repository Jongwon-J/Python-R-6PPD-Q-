# --- EcoBridge-6PPDQ 백엔드(FastAPI) 이미지 ---
FROM python:3.12-slim

WORKDIR /app

# 로그 시각 등을 한국 시간(KST) 기준으로 보기 위한 시간대 설정
ENV TZ=Asia/Seoul

# psycopg2 빌드에 필요한 라이브러리 (psycopg2-binary는 보통 불필요하지만, 안전하게 포함)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc tzdata \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

COPY app/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY frontend/ ./frontend/

EXPOSE 8000

# 여러 워커로 띄워 동시 요청을 나눠 처리 (부하 테스트 대비)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
