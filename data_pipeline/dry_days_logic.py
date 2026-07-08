"""
dry_days_logic.py
선행 무강우일수(Antecedent Dry Days, ADD) 계산 알고리즘

정의: 특정 날짜 기준으로, "무강우 기준치(threshold_mm)" 미만의 비가 내린 날이 연속으로
      며칠째 이어지고 있는지 계산합니다. 기준치 이상 비가 온 날은 카운트가 0으로 리셋됩니다.

실행 모드:
    python dry_days_logic.py backfill [--start-date YYYY-MM-DD] [--end-date YYYY-MM-DD]
        -> weather_raw에 쌓인 과거 데이터를 처음부터(또는 지정 구간) 역산하여
           dry_days_status 테이블을 전체 재계산합니다.
    python dry_days_logic.py daily
        -> 어제 하루치만 반영하여 카운터를 1건 갱신합니다. (cron으로 매일 00:10 실행 권장)
"""

import os
import argparse
import logging
from datetime import date, timedelta
from typing import List, Tuple, Optional

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("dry_days_logic")

DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "localhost"),
    "port": os.environ.get("DB_PORT", "5432"),
    "dbname": os.environ["DB_NAME"],
    "user": os.environ["DB_USER"],
    "password": os.environ["DB_PASSWORD"],
}

# .env에 값이 있으면 그 값을, 없으면 문자열 "1.0" 을 가져온다.
DRY_DAY_THRESHOLD_MM = float(os.environ.get("DRY_DAY_THRESHOLD_MM", "1.0"))


def get_conn():
    return psycopg2.connect(**DB_CONFIG)

"""weather_raw의 시간당 강수량(rn1_mm)을 날짜별로 합산"""
def fetch_daily_precip(cur, nx: int, ny: int, start_date: date, end_date: date) -> List[Tuple[date, float]]:
    cur.execute(
        """
        SELECT obs_datetime::date AS obs_date, COALESCE(SUM(rn1_mm), 0) AS daily_mm
        FROM weather_raw
        WHERE nx = %s AND ny = %s
          AND obs_datetime::date BETWEEN %s AND %s
        GROUP BY obs_datetime::date
        ORDER BY obs_datetime::date
        """,
        (nx, ny, start_date, end_date),
    )
    return cur.fetchall()

"""날짜순으로 정렬된 (date, daily_mm) 리스트를 받아 각 날짜별 선행 무강우일수를 계산."""
def calculate_antecedent_dry_days(
    daily_rows: List[Tuple[date, float]], threshold_mm: float, carry_in: int = 0
) -> List[Tuple[date, float, bool, int]]:
    
    result = []
    running = carry_in # carry_in: 시작일 이전까지 이미 누적된 무강우일수
    for obs_date, daily_mm in daily_rows:
        daily_mm = float(daily_mm)
        is_dry = daily_mm < threshold_mm # threshold_mm : 기준 강수량
        running = running + 1 if is_dry else 0
        result.append((obs_date, daily_mm, is_dry, running))
    return result

"""여러 행을 한 번에 저장"""
def upsert_dry_days(cur, nx: int, ny: int, rows: List[Tuple[date, float, bool, int]]) -> None:
    sql = """
        INSERT INTO dry_days_status (obs_date, nx, ny, daily_precip_mm, is_dry_day, antecedent_dry_days)
        VALUES %s
        ON CONFLICT (obs_date, nx, ny)
        DO UPDATE SET
            daily_precip_mm = EXCLUDED.daily_precip_mm,
            is_dry_day = EXCLUDED.is_dry_day,
            antecedent_dry_days = EXCLUDED.antecedent_dry_days,
            updated_at = now();
    """
    values = [(obs_date, nx, ny, daily_mm, is_dry, add) for obs_date, daily_mm, is_dry, add in rows]
    psycopg2.extras.execute_values(cur, sql, values)

"""start_date 직전 날짜의 누적 무강우일수를 조회 (구간 앞쪽 연속성 유지용). 없으면 0."""
def get_carry_in(cur, nx: int, ny: int, before_date: date) -> int:
    cur.execute(
        """
        SELECT antecedent_dry_days FROM dry_days_status
        WHERE nx = %s AND ny = %s AND obs_date < %s
        ORDER BY obs_date DESC LIMIT 1
        """,
        (nx, ny, before_date),
    )
    row = cur.fetchone()
    return row[0] if row else 0


def run_backfill(nx: int, ny: int, start_date: Optional[date], end_date: Optional[date]):
    conn = get_conn()
    try:
        with conn, conn.cursor() as cur:
            
            if end_date is None: # 끝 지점 안 정해졌을 경우
                end_date = date.today() - timedelta(days=1)

            if start_date is None: # 시작 지점 안 정해졌을 경우
                cur.execute(
                    "SELECT MIN(obs_datetime::date) FROM weather_raw WHERE nx=%s AND ny=%s", (nx, ny)
                )
                row = cur.fetchone()
                if not row or row[0] is None:
                    logger.warning("weather_raw에 해당 지점(nx, ny) 데이터가 없습니다. 먼저 weather_collector.py를 실행하세요.")
                    return
                start_date = row[0]

            if start_date > end_date:
                logger.warning(
                    f"아직 완결된 하루치 데이터가 없습니다 (수집된 가장 이른 날짜={start_date}, "
                    f"오늘은 미완결이라 제외됨). weather_collector.py를 자정 이후까지 더 돌린 뒤 다시 실행하세요."
                )
                return
            
            carry_in = get_carry_in(cur, nx, ny, start_date)
            daily_rows = fetch_daily_precip(cur, nx, ny, start_date, end_date)
            if not daily_rows:
                logger.warning(f"{start_date} ~ {end_date} 구간에 weather_raw 데이터가 없습니다.")
                return

            computed = calculate_antecedent_dry_days(daily_rows, DRY_DAY_THRESHOLD_MM, carry_in)
            upsert_dry_days(cur, nx, ny, computed)
            logger.info(
                f"백필 완료: {start_date} ~ {end_date}, {len(computed)}일 처리 "
                f"(임계값={DRY_DAY_THRESHOLD_MM}mm, carry_in={carry_in})"
            )
    finally:
        conn.close()

"""하루 실행용 간편 버전"""
def run_daily(nx: int, ny: int):
    target_date = date.today() - timedelta(days=1)
    run_backfill(nx, ny, target_date, target_date)


def get_all_road_grid_points() -> List[Tuple[int, int]]:
    """
    road_master에 지오코딩된 도로들이 흩어져 있는 서로 다른 모든 격자(nx, ny) 목록을 반환합니다.
    도로마다 위치(격자)가 다르므로, 무강우일수도 각 도로의 격자별로 따로 계산해야
    etl_risk_pipeline.py가 모든 도로에 대해 값을 찾을 수 있습니다.
    road_master가 비어 있으면 빈 리스트를 반환합니다 (호출부에서 --nx/--ny 폴백 처리).
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT nx, ny FROM road_master WHERE nx IS NOT NULL AND ny IS NOT NULL"
            )
            return cur.fetchall()
    finally:
        conn.close()

"""실행부"""
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="선행 무강우일수(ADD) 계산")
    parser.add_argument("mode", choices=["backfill", "daily"])
    parser.add_argument("--start-date", type=lambda s: date.fromisoformat(s), default=None)
    parser.add_argument("--end-date", type=lambda s: date.fromisoformat(s), default=None)
    parser.add_argument("--nx", type=int, default=int(os.environ.get("TANCHEON_NX", "62")))
    parser.add_argument("--ny", type=int, default=int(os.environ.get("TANCHEON_NY", "123")))
    args = parser.parse_args()

    grid_points = get_all_road_grid_points()
    if not grid_points:
        logger.warning(
            "road_master가 비어 있어 --nx/--ny(.env TANCHEON_NX/NY) 지점 하나만 계산합니다. "
            "geocode_and_import_road_master.py 실행 후 다시 돌리면 도로별 격자를 자동으로 잡습니다."
        )
        grid_points = [(args.nx, args.ny)]
    else:
        logger.info(f"road_master 기준 대상 격자 {len(grid_points)}개: {grid_points}")

    for nx, ny in grid_points:
        if args.mode == "backfill":
            run_backfill(nx, ny, args.start_date, args.end_date)
        else:
            run_daily(nx, ny)
