"""
risk_alert_log의 미처리(notified=false) 등급 상승 이벤트를 행정 공문서 양식으로 변환하고
SMS로 발송하는 CrewAI 에이전트.

환각 방지: 문서번호/수신/위험도점수 등 사실 필드는 전부 Python이 DB 값으로 직접 채우고
(render_document), LLM에게는 등급별 "권고 조치사항" 두 문장만 생성하도록 범위를 좁혔다.

    python crew_alert_agent.py
"""

import os
import sys
import logging
from datetime import datetime

import psycopg2
from dotenv import load_dotenv
from crewai import Agent, Task, Crew, LLM

from sms_notifier import send_sms

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

# 짧은 문장 2개만 생성하므로 무료 티어인 gemini-3.5-flash 사용.
llm = LLM(
    model="gemini/gemini-3.5-flash",
    api_key=os.environ["GEMINI_API_KEY"],
    temperature=0.3,
)

# 윤서의 "등급별 프롬프트 가이드" 표를 그대로 반영 (표현 규칙 + 금지 사항).
GRADE_ADVISORY_RULES = {
    "관심": {
        "rule": "\"모니터링을 지속하며 특이사항 없음\" 수준의 담담한 표현만 사용",
        "forbidden": "긴급성 강조, 대피·경고성 문구 사용 금지",
    },
    "주의": {
        "rule": "\"인근 주민은 하천 접촉을 자제해 주시기 바랍니다\" 등 예방적 권고 표현",
        "forbidden": "확정되지 않은 피해 규모 언급 금지",
    },
    "경계": {
        "rule": "\"현장 점검을 실시하며, 필요시 접근을 통제할 수 있습니다\" 등 대응 준비 표현",
        "forbidden": "구체적 수치(ng/L 등 미실측값) 추정 금지",
    },
    "심각": {
        "rule": "\"즉시 현장 접근을 제한하고 관계기관에 통보합니다\" 등 명확한 조치 지시",
        "forbidden": "법령 근거는 실제 확인된 조문만 인용, 임의 법령 생성 금지",
    },
}

COMMON_CONSTRAINTS = (
    "1) 제공된 위험도 점수·AADT·불투수면비율 외의 수치를 추측해 생성하지 않는다 "
    "(실측 6PPD-Q 농도 ng/L 값은 계산된 적 없으므로 절대 언급 금지)\n"
    "2) 본 위험도는 시뮬레이션 기반 지표이며 실측 오염도가 아니다\n"
    "3) 법령·정책 근거는 「재난 및 안전관리 기본법」 제38조 외에는 인용하지 않는다\n"
    "4) 등급 경계값(33.5/40.5/49.9)은 현재 표본(n=15) 기준 상대치다"
)

advisory_writer = Agent(
    role="6PPD-Q 하천 위험도 경보 공문서 작성자",
    goal="등급별 표현 규칙을 지키면서, 행정 담당자용 조치 문장과 시민 안내용 문장을 각각 한 문장씩 작성한다.",
    backstory=(
        "너는 탄천 유역 6PPD-Q 유입 조기경보 대시보드의 경보 문서 작성 담당이다. "
        "공문서의 숫자·사실 필드는 이미 시스템이 채워두었고, 너는 오직 '권고 조치사항' 두 문장만 작성한다. "
        f"반드시 지켜야 할 공통 제약:\n{COMMON_CONSTRAINTS}"
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
        SELECT a.id, a.road_id, r.road_name, r.gu, r.tributary, r.aadt, r.impervious_ratio,
               a.calc_datetime, a.prev_grade, a.new_grade, a.risk_score
        FROM risk_alert_log a
        JOIN road_master r ON r.road_id = a.road_id
        WHERE a.notified = false
        ORDER BY a.calc_datetime
        """
    )
    cols = ["id", "road_id", "road_name", "gu", "tributary", "aadt", "impervious_ratio",
            "calc_datetime", "prev_grade", "new_grade", "risk_score"]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def mark_notified(cur, alert_id: int, document_text: str):
    cur.execute(
        "UPDATE risk_alert_log SET notified = true, document_text = %s WHERE id = %s",
        (document_text, alert_id),
    )


def build_advisory_task(alert: dict) -> Task:
    """LLM에게는 등급/규칙만 주고, 위험도 수치나 법령 문구는 참고용으로만 노출 (직접 인용 대상 아님)."""
    grade = alert["new_grade"]
    rules = GRADE_ADVISORY_RULES.get(grade, GRADE_ADVISORY_RULES["관심"])
    description = (
        f"등급 '{grade}'에 대한 권고 조치사항을 딱 두 줄로 작성해줘.\n"
        f"- 표현 규칙: {rules['rule']}\n"
        f"- 금지 사항: {rules['forbidden']}\n"
        "출력 형식은 반드시 아래 두 줄 그대로 (다른 말 붙이지 말 것):\n"
        "행정: <행정 담당자용 조치 문장 1개>\n"
        "시민: <시민 안내용 문장 1개>"
    )
    return Task(
        description=description,
        expected_output="'행정: ...' 줄과 '시민: ...' 줄, 정확히 두 줄",
        agent=advisory_writer,
    )


def parse_advisory(raw_text: str) -> tuple:
    """'행정: ...' / '시민: ...' 두 줄을 파싱. 형식이 어긋나면 원문 그대로를 두 필드에 채워 보존."""
    admin_line, citizen_line = "", ""
    for line in str(raw_text).splitlines():
        line = line.strip()
        if line.startswith("행정:"):
            admin_line = line.removeprefix("행정:").strip()
        elif line.startswith("시민:"):
            citizen_line = line.removeprefix("시민:").strip()
    if not admin_line and not citizen_line:
        admin_line = citizen_line = str(raw_text).strip()
    return admin_line, citizen_line


def render_document(alert: dict, admin_sentence: str, citizen_sentence: str) -> str:
    """윤서의 '행정 공문서 표준 양식'에 맞춰 최종 경보 문서를 조립 (전부 결정론적 치환, LLM 개입 없음)."""
    doc_no = f"환경과-{alert['calc_datetime'].year}-{alert['id']:04d}"
    calc_dt_display = alert["calc_datetime"].strftime("%Y-%m-%d %H:%M")
    return (
        "6PPD-Q 하천 오염 위험도 경보 발령 안내\n"
        f"문서번호   : {doc_no}\n"
        f"수신       : {alert['gu']}청장 / 환경과\n"
        f"시행일시   : {calc_dt_display}\n"
        f"제목       : [{alert['new_grade']}] {alert['tributary']} {alert['road_name']} 6PPD-Q 위험도 경보 발령\n"
        "\n"
        "1. 관련: 「재난 및 안전관리 기본법」 제38조(위기경보의 발령)\n"
        "2. 발령 개요\n"
        f"   - 지점        : {alert['road_name']} ({alert['gu']} · {alert['tributary']})\n"
        f"   - 위험도 점수  : {alert['risk_score']}점 / 100\n"
        f"   - 경보 등급    : {alert['new_grade']} (직전: {alert['prev_grade']})\n"
        "   - 산정 기준    : 위험도 = 부하지수(AADT·건조일수) x 유출지수(강수강도·불투수면) x 100\n"
        f"   - 관측 AADT    : {alert['aadt']}대/일\n"
        f"   - 불투수면비율  : {alert['impervious_ratio']}%\n"
        "\n"
        "3. 권고 조치사항\n"
        f"   행정: {admin_sentence}\n"
        f"   시민: {citizen_sentence}\n"
        "\n"
        "붙임: 1. 위험도 산정 근거자료 1부. 2. GIS 위치도 1부. 끝.\n"
        f"\n{alert['gu']}청장 (직인)"
    )


def build_official_sms_text(alert: dict, admin_sentence: str) -> str:
    """담당 공무원에게 보낼 SMS 문구."""
    return (
        f"[6PPD-Q 위험도 경보] {alert['tributary']} {alert['road_name']}({alert['gu']}) "
        f"{alert['prev_grade']}->{alert['new_grade']} (위험도 {alert['risk_score']}점)\n{admin_sentence}"
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
                task = build_advisory_task(alert)
                crew = Crew(agents=[advisory_writer], tasks=[task], verbose=False)
                result = crew.kickoff()
                admin_sentence, citizen_sentence = parse_advisory(result)

                document = render_document(alert, admin_sentence, citizen_sentence)
                logger.info(f"[ALERT #{alert['id']}] 문서 생성 완료\n{document}")

                sms_text = build_official_sms_text(alert, admin_sentence)
                send_sms(sms_text)

                mark_notified(cur, alert["id"], document)
                processed += 1

        logger.info(f"완료: 경보 문서 {processed}건 생성")
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        logger.error(f"CrewAI 알림 처리 실패: {e}")
        sys.exit(1)
