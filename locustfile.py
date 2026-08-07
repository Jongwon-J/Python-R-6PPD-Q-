"""
locustfile.py — EcoBridge-6PPDQ 백엔드 부하 테스트.

실행 방법:
    pip install locust
    locust -f locustfile.py --host http://127.0.0.1:8000

웹 UI(기본 http://localhost:8089)에서 동시 사용자 수, 스폰 속도를 지정해서 실행.
"""

import random

from locust import HttpUser, task, between


class DashboardUser(HttpUser):
    """대시보드를 보는 일반 사용자 시나리오. 조회가 대부분, 쓰기는 드물게."""

    wait_time = between(1, 3)

    @task(5)
    def view_health(self):
        self.client.get("/health")

    @task(10)
    def view_risk_roads(self):
        """가장 자주 호출되는 엔드포인트 — 대시보드가 1분마다 폴링하는 화면"""
        self.client.get("/risk/roads")

    @task(6)
    def view_reports(self):
        self.client.get("/reports/")

    @task(3)
    def view_documents(self):
        self.client.get("/documents/")

    @task(1)
    def submit_report(self):
        """시민 제보 등록 — 쓰기 작업, DB insert + 트랜잭션 확인용"""
        lat = round(random.uniform(37.40, 37.55), 6)
        lon = round(random.uniform(127.00, 127.12), 6)
        self.client.post(
            "/reports/",
            data={
                "lat": lat,
                "lon": lon,
                "description": "부하 테스트 자동 생성 제보",
            },
        )
