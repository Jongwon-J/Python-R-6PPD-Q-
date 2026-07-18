"""
etl_risk_pipeline.py - 3주차 핵심 산출물
weather_raw + dry_days_status + road_master를 (nx, ny) 격자 기준으로 조인해서,
도로별 위험도를 risk_formula.py로 계산한 뒤 processed_risk_log에 적재하는 배치 스크립트.

실행:
    python etl_risk_pipeline.py

cron 예시 (10분마다, weather_collector.py 실행 직후):
    */10 * * * * cd /path/to/project/data_pipeline && venv/bin/python weather_collector.py && venv/bin/python etl_risk_pipeline.py

[핵심 로직 - 강우 이벤트 판정]
risk_formula.py의 rainfall_trigger()는 "강우가 시작된 지 몇 시간째이고 그동안 몇 mm가
누적됐는지"를 미리 계산해서 받는다는 전제로 만들어졌습니다 (risk_formula.py 문서 참고).
weather_raw에는 매시간 강수량(rn1_mm)만 있고 "언제부터 연속으로 비가 왔는지"는 없기 때문에,
get_rain_event_state()에서 이 판정 로직을 직접 구현합니다.
"""

import os
import sys
import logging
from datetime import datetime, timedelta
from typing import Optional, Tuple, List

import psycopg2
from dotenv import load_dotenv

from risk_formula import calculate_full_risk

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("etl_risk_pipeline")

DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "localhost"),
    "port": os.environ.get("DB_PORT", "5432"),
    "dbname": os.environ["DB_NAME"],
    "user": os.environ["DB_USER"],
    "password": os.environ["DB_PASSWORD"],
}

# 최근 몇 시간까지 거슬러 올라가며 연속 강우 이벤트를 찾을지 (하루면 충분하다고 가정)
RAIN_LOOKBACK_HOURS = 24

# 등급 순위 (임계치 트리거 판정용). risk_formula.RISK_GRADE_BOUNDARIES와 순서를 맞춰야 함.
GRADE_RANK = {"관심": 0, "주의": 1, "경계": 2, "심각": 3}


def get_conn():
    return psycopg2.connect(**DB_CONFIG)


def get_aadt_sample_range(cur) -> Tuple[float, float]:
    """road_master 표본 내 AADT 최소/최대값 (정규화 기준)."""
    cur.execute("SELECT MIN(aadt), MAX(aadt) FROM road_master WHERE aadt IS NOT NULL")
    row = cur.fetchone()
    return float(row[0]), float(row[1])


def get_impervious_sample_range(cur) -> Tuple[float, float]:
    """road_master 표본 내 불투수면비율 최소/최대값 (정규화 기준).
    불투수면 정규화를 값/100 절대 스케일에서 표본 상대 min-max로 바꾸면서 추가됨."""
    cur.execute("SELECT MIN(impervious_ratio), MAX(impervious_ratio) FROM road_master WHERE impervious_ratio IS NOT NULL")
    row = cur.fetchone()
    return float(row[0]), float(row[1])


def get_roads(cur) -> List[dict]:
    """위험도 계산에 필요한 값이 전부 채워진 도로만 대상으로 함 (지오코딩/CSV 값 누락 시 제외)."""
    cur.execute(
        """
        SELECT road_id, road_name, aadt, impervious_ratio, nx, ny
        FROM road_master
        WHERE aadt IS NOT NULL AND impervious_ratio IS NOT NULL
          AND nx IS NOT NULL AND ny IS NOT NULL
        """
    )
    cols = ["road_id", "road_name", "aadt", "impervious_ratio", "nx", "ny"]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def get_latest_dry_days(cur, nx: int, ny: int) -> Optional[int]:
    """해당 격자의 가장 최근 선행 무강우일수. 아직 계산된 값이 없으면 None."""
    cur.execute(
        """
        SELECT antecedent_dry_days FROM dry_days_status
        WHERE nx = %s AND ny = %s
        ORDER BY obs_date DESC LIMIT 1
        """,
        (nx, ny),
    )
    row = cur.fetchone()
    return int(row[0]) if row else None


def get_rain_event_state(cur, nx: int, ny: int) -> Tuple[bool, float, float, Optional[float], Optional[datetime]]:
    """
    반환: (is_raining, cumulative_mm_since_rain_start, hours_since_rain_start,
           latest_rn1_mm, latest_obs_datetime)
    최신 관측치가 없으면 (False, 0.0, 0.0, None, None).
    """
    cur.execute(
        """
        SELECT obs_datetime, rn1_mm FROM weather_raw
        WHERE nx = %s AND ny = %s
          AND obs_datetime >= %s
        ORDER BY obs_datetime DESC
        """,
        (nx, ny, datetime.now() - timedelta(hours=RAIN_LOOKBACK_HOURS)),
    )
    rows = cur.fetchall()  # 최신순 (내림차순)
    if not rows:
        logger.warning(f"nx={nx} ny={ny}: 최근 {RAIN_LOOKBACK_HOURS}시간 내 weather_raw 데이터 없음")
        return False, 0.0, 0.0, None, None

    latest_dt, latest_rn1 = rows[0]
    latest_rn1 = float(latest_rn1) if latest_rn1 is not None else 0.0

    if latest_rn1 <= 0:
        return False, 0.0, 0.0, latest_rn1, latest_dt

    # 최신 시각부터 거슬러 올라가며 "끊기지 않고 이어지는" 강우 구간을 누적
    cumulative_mm = 0.0
    hours = 0
    expected_dt = latest_dt
    for obs_dt, rn1 in rows:
        rn1 = float(rn1) if rn1 is not None else 0.0
        if obs_dt != expected_dt:
            break  # 관측 데이터 자체가 비어 있는 시간대 -> 연속 구간 종료
        if rn1 <= 0:
            break  # 비가 그친 시점 -> 연속 구간 종료
        cumulative_mm += rn1
        hours += 1
        expected_dt = obs_dt - timedelta(hours=1)

    return True, round(cumulative_mm, 2), float(hours), latest_rn1, latest_dt


def upsert_risk_log(cur, road_id: str, calc_datetime: datetime, rn1_mm: Optional[float],
                     antecedent_dry_days: int, aadt: int, impervious_ratio: float, result: dict):
    sql = """
        INSERT INTO processed_risk_log
            (road_id, calc_datetime, rn1_mm, antecedent_dry_days, aadt, impervious_ratio,
             aadt_norm, dry_days_norm, rain_trigger, impervious_norm, load_index, runoff_index,
             risk_score, risk_grade)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (road_id, calc_datetime)
        DO UPDATE SET
            rn1_mm = EXCLUDED.rn1_mm,
            antecedent_dry_days = EXCLUDED.antecedent_dry_days,
            aadt_norm = EXCLUDED.aadt_norm,
            dry_days_norm = EXCLUDED.dry_days_norm,
            rain_trigger = EXCLUDED.rain_trigger,
            impervious_norm = EXCLUDED.impervious_norm,
            load_index = EXCLUDED.load_index,
            runoff_index = EXCLUDED.runoff_index,
            risk_score = EXCLUDED.risk_score,
            risk_grade = EXCLUDED.risk_grade;
    """
    cur.execute(sql, (
        road_id, calc_datetime, rn1_mm, antecedent_dry_days, aadt, impervious_ratio,
        result["aadt_norm"], result["dry_days_norm"], result["rain_trigger"], result["impervious_norm"],
        result["load_index"], result["runoff_index"], result["risk_score"], result["risk_grade"],
    ))


def get_previous_risk_grade(cur, road_id: str, before_datetime: datetime) -> Optional[str]:
    """해당 도로의 이번 계산 시각(before_datetime)보다 앞선 가장 최근 등급. 없으면 None(최초 계산)."""
    cur.execute(
        """
        SELECT risk_grade FROM processed_risk_log
        WHERE road_id = %s AND calc_datetime < %s AND risk_grade IS NOT NULL
        ORDER BY calc_datetime DESC LIMIT 1
        """,
        (road_id, before_datetime),
    )
    row = cur.fetchone()
    return row[0] if row else None


def maybe_log_alert(cur, road_id: str, calc_datetime: datetime, prev_grade: Optional[str],
                     new_grade: str, risk_score: float) -> bool:
    """
    등급이 "상승"한 경우에만 risk_alert_log에 기록하고 True를 반환.
    직전 기록이 없는 최초 계산은 비교 대상이 없으므로 트리거하지 않음(백필 시 노이즈 방지).
    """
    if prev_grade is None:
        return False
    if GRADE_RANK.get(new_grade, 0) <= GRADE_RANK.get(prev_grade, 0):
        return False

    cur.execute(
        """
        INSERT INTO risk_alert_log (road_id, calc_datetime, prev_grade, new_grade, risk_score)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (road_id, calc_datetime, prev_grade, new_grade, risk_score),
    )
    return True


def run():
    conn = get_conn()
    processed, skipped, alerts = 0, 0, 0
    try:
        with conn, conn.cursor() as cur:
            aadt_min, aadt_max = get_aadt_sample_range(cur)
            impervious_min, impervious_max = get_impervious_sample_range(cur)
            roads = get_roads(cur)
            if not roads:
                logger.warning("road_master에 위험도 계산 가능한 도로가 없습니다. "
                                "import_gis_road_master.py(또는 geocode_and_import_road_master.py)를 먼저 실행하세요.")
                return

            for road in roads:
                nx, ny = road["nx"], road["ny"]

                antecedent_dry_days = get_latest_dry_days(cur, nx, ny)
                if antecedent_dry_days is None:
                    logger.warning(f"{road['road_id']} {road['road_name']}: dry_days_status 데이터 없음, 건너뜀 "
                                    f"(dry_days_logic.py backfill을 먼저 실행하세요)")
                    skipped += 1
                    continue

                is_raining, cum_mm, hours_since_start, rn1_mm, obs_dt = get_rain_event_state(cur, nx, ny)
                if obs_dt is None:
                    logger.warning(f"{road['road_id']} {road['road_name']}: weather_raw 데이터 없음, 건너뜀")
                    skipped += 1
                    continue

                result = calculate_full_risk(
                    aadt=road["aadt"],
                    aadt_sample_min=aadt_min,
                    aadt_sample_max=aadt_max,
                    antecedent_dry_days=antecedent_dry_days,
                    is_raining=is_raining,
                    impervious_ratio_pct=float(road["impervious_ratio"]),
                    impervious_sample_min=impervious_min,
                    impervious_sample_max=impervious_max,
                    cumulative_mm_since_rain_start=cum_mm,
                    hours_since_rain_start=hours_since_start,
                )

                prev_grade = get_previous_risk_grade(cur, road["road_id"], obs_dt)

                upsert_risk_log(
                    cur, road["road_id"], obs_dt, rn1_mm, antecedent_dry_days,
                    road["aadt"], float(road["impervious_ratio"]), result,
                )

                triggered = maybe_log_alert(
                    cur, road["road_id"], obs_dt, prev_grade, result["risk_grade"], result["risk_score"],
                )
                if triggered:
                    alerts += 1
                    logger.warning(
                        f"[ALERT] {road['road_id']} {road['road_name']}: "
                        f"{prev_grade} -> {result['risk_grade']} (risk_score={result['risk_score']})"
                    )

                logger.info(
                    f"{road['road_id']} {road['road_name']}: risk_score={result['risk_score']} "
                    f"grade={result['risk_grade']} (is_raining={is_raining}, ADD={antecedent_dry_days}, rn1={rn1_mm})"
                )
                processed += 1

        logger.info(
            f"ETL 완료: 처리 {processed}건, 건너뜀 {skipped}건, 등급 상승 트리거 {alerts}건 "
            f"(표본 AADT 범위 {aadt_min}~{aadt_max})"
        )
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        logger.error(f"ETL 실패: {e}")
        sys.exit(1)
