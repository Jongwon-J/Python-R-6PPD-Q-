"""
crew_alert_agent.py - CrewAI 기반 위험도 알림 리포팅 에이전트

역할:
    etl_risk_pipeline.py가 위험도 등급 상승을 감지해 risk_alert_log에 남겨둔 이벤트(notified=false)를
    읽어서, CrewAI 에이전트가 담당자용 한국어 알림 문장을 생성하고 notified=true로 표시합니다.

주의:
    이 에이전트는 "위험도 계산 정확도"를 개선하지 않습니다 (그건 risk_formula.py의 역할).
    여기서 하는 일은 이미 계산이 끝난 숫자를 사람이 읽기 좋은 문장으로 바꿔주는 리포팅 레이어입니다.

LLM:
    Google Gemini를 사용합니다 (gemini-3.5-flash, 무료 티어). GEMINI_API_KEY가 필요하며,
    aistudio.google.com에서 카드 등록 없이 무료로 발급받을 수 있습니다 (분당/일일 요청 수 제한 있음).
    (gemini-2.0-flash는 2026-06-01자로 셧다운되어 더 이상 사용 불가 — gemini-3.5-flash로 대체.)

실행:
    python crew_alert_agent.py

cron 예시 (etl_risk_pipeline.py 실행 직후):
    */10 * * * * cd /path/to/project/data_pipeline && venv/bin/python weather_collector.py && venv/bin/python etl_risk_pipeline.py && venv/bin/python crew_alert_agent.py
"""

import os
import sys
import logging

import psycopg2
from dotenv import load_dotenv
from crewai import Agent, Task, Crew, LLM

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("crew_alert_agent")

DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "localhost"),
    "port": os.environ.get("DB_PORT", "5432"),
    "dbname": os.environ["DB_NAME"],
    "user": os.environ["DB_USER"],
    "password": os.environ["DB_PASSWORD"],
}

# 등급 상승 문장 하나 생성하는 가벼운 작업이라, 무료 티어인 gemini-3.5-flash를 기본으로 사용.
llm = LLM(
    model="gemini/gemini-3.5-flash",
    api_key=os.environ["GEMINI_API_KEY"],
    temperature=0.3,
)

alert_writer = Agent(
    role="6PPD-Q 하천 위험도 알림 작성자",
    goal="위험도 등급이 상승한 도로에 대해, 담당자가 바로 상황을 이해할 수 있는 짧고 명확한 한국어 알림 문장을 작성한다.",
    backstory=(
        "너는 탄천 유역 6PPD-Q 유입 조기경보 대시보드의 알림 담당이다. "
        "숫자로 된 위험도 계산 결과를 받아서, 비전문가도 바로 이해할 수 있는 알림 메시지로 바꾸는 역할을 한다."
    ),
    llm=llm,
    verbose=True,
)


def get_conn():
    return psycopg2.connect(**DB_CONFIG)


def get_pending_alerts(cur):
    """아직 처리하지 않은(notified=false) 등급 상승 이벤트를 도로 정보와 함께 조회."""
    cur.execute(
        """
        SELECT a.id, a.road_id, r.road_name, r.gu, a.calc_datetime, a.prev_grade, a.new_grade, a.risk_score
        FROM risk_alert_log a
        JOIN road_master r ON r.road_id = a.road_id
        WHERE a.notified = false
        ORDER BY a.calc_datetime
        """
    )
    cols = ["id", "road_id", "road_name", "gu", "calc_datetime", "prev_grade", "new_grade", "risk_score"]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def mark_notified(cur, alert_id: int):
    cur.execute("UPDATE risk_alert_log SET notified = true WHERE id = %s", (alert_id,))


def build_alert_task(alert: dict) -> Task:
    description = (
        "다음 위험도 등급 상승 이벤트에 대한 알림 문장을 한국어로 2~3문장 작성해줘.\n"
        f"- 도로: {alert['road_name']} ({alert['gu']})\n"
        f"- 계산 시각: {alert['calc_datetime']}\n"
        f"- 등급 변화: {alert['prev_grade']} -> {alert['new_grade']}\n"
        f"- 위험도 점수: {alert['risk_score']}점\n"
        "과장하지 말고, 담당자가 바로 현장 확인 여부를 판단할 수 있게 사실 위주로 작성해."
    )
    return Task(
        description=description,
        expected_output="2~3문장의 한국어 알림 메시지",
        agent=alert_writer,
    )


def run():
    conn = get_conn()
    processed = 0
    try:
        with conn, conn.cursor() as cur:
            alerts = get_pending_alerts(cur)
            if not alerts:
                logger.info("처리할 알림 없음 (notified=false인 risk_alert_log 없음)")
                return

            for alert in alerts:
                task = build_alert_task(alert)
                crew = Crew(agents=[alert_writer], tasks=[task], verbose=False)
                result = crew.kickoff()

                logger.info(f"[ALERT #{alert['id']}] {alert['road_name']}: {result}")
                mark_notified(cur, alert["id"])
                processed += 1

        logger.info(f"완료: 알림 {processed}건 생성")
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        logger.error(f"CrewAI 알림 처리 실패: {e}")
        sys.exit(1)
