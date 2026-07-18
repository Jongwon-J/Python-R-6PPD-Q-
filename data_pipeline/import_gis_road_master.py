"""
import_gis_road_master.py
gis_mapping_data.csv(윤서 GIS 검증용 15개 도로 표본)를 읽어 road_master 테이블에 적재합니다.

geocode_and_import_road_master.py와의 차이:
    tancheon_week2_final.csv는 "행정동" 주소만 있어서 카카오 API로 지오코딩(주소->위경도)이
    필요했지만, gis_mapping_data.csv는 위도/경도가 이미 값으로 들어 있으므로 지오코딩 단계를
    건너뛰고 dfs_xy_conv()로 기상 격자좌표(nx, ny)만 계산해서 바로 적재합니다.

CSV 컬럼 (data/gis_mapping_data.csv):
    도로ID,도로명,소속구,지류,위도,경도,AADT,불투수면,위험도
    - "지류", "위험도"는 road_master 스키마에 없는 컬럼이라 적재하지 않습니다.
      (위험도는 참고용으로 윤서가 미리 계산해둔 값이고, 실제 서비스에서 쓰는 위험도는
      etl_risk_pipeline.py가 매번 새로 계산해서 processed_risk_log에 남깁니다.)
    - 행정동/도로연장_km/차선수/기준년도/출처_AADT/출처_불투수면은 이 CSV에 없어서 NULL로 둡니다
      (road_master에서 전부 nullable 컬럼).

사용법:
    python import_gis_road_master.py [--csv data/gis_mapping_data.csv]
"""

import os
import csv
import sys
import math
import logging
import argparse
from typing import Optional, Tuple, Dict

import psycopg2
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("import_gis_road_master")

DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "localhost"),
    "port": os.environ.get("DB_PORT", "5432"),
    "dbname": os.environ["DB_NAME"],
    "user": os.environ["DB_USER"],
    "password": os.environ["DB_PASSWORD"],
}

DEFAULT_CSV_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "gis_mapping_data.csv"
)


# ---------------------------------------------------------------------------
# 격자좌표 변환 (weather_collector.py / geocode_and_import_road_master.py와 동일 로직).
# 세 스크립트가 서로 import하지 않고 독립 실행 가능하도록 의도적으로 중복 구현함.
# ---------------------------------------------------------------------------
def dfs_xy_conv(lat: float, lon: float) -> Tuple[int, int]:
    RE = 6371.00877
    GRID = 5.0
    SLAT1, SLAT2 = 30.0, 60.0
    OLON, OLAT = 126.0, 38.0
    XO, YO = 43, 136

    DEGRAD = math.pi / 180.0
    re = RE / GRID
    slat1, slat2 = SLAT1 * DEGRAD, SLAT2 * DEGRAD
    olon, olat = OLON * DEGRAD, OLAT * DEGRAD

    sn = math.tan(math.pi * 0.25 + slat2 * 0.5) / math.tan(math.pi * 0.25 + slat1 * 0.5)
    sn = math.log(math.cos(slat1) / math.cos(slat2)) / math.log(sn)
    sf = math.tan(math.pi * 0.25 + slat1 * 0.5)
    sf = math.pow(sf, sn) * math.cos(slat1) / sn
    ro = math.tan(math.pi * 0.25 + olat * 0.5)
    ro = re * sf / math.pow(ro, sn)

    ra = math.tan(math.pi * 0.25 + lat * DEGRAD * 0.5)
    ra = re * sf / math.pow(ra, sn)
    theta = lon * DEGRAD - olon
    if theta > math.pi:
        theta -= 2.0 * math.pi
    if theta < -math.pi:
        theta += 2.0 * math.pi
    theta *= sn

    x = math.floor(ra * math.sin(theta) + XO + 0.5)
    y = math.floor(ro - ra * math.cos(theta) + YO + 0.5)
    return int(x), int(y)


def read_csv(csv_path: str):
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    logger.info(f"CSV 로드 완료: {csv_path} ({len(rows)}행)")
    return rows


def _to_int(v, default=None):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _to_float(v, default=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def upsert_road(cur, row: Dict, lat: float, lon: float, nx: int, ny: int):
    sql = """
        INSERT INTO road_master
            (road_id, road_name, gu, aadt, impervious_ratio, lat, lon, nx, ny, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now())
        ON CONFLICT (road_id)
        DO UPDATE SET
            road_name = EXCLUDED.road_name,
            gu = EXCLUDED.gu,
            aadt = EXCLUDED.aadt,
            impervious_ratio = EXCLUDED.impervious_ratio,
            lat = EXCLUDED.lat,
            lon = EXCLUDED.lon,
            nx = EXCLUDED.nx,
            ny = EXCLUDED.ny,
            updated_at = now();
    """
    cur.execute(sql, (
        row["도로ID"],
        row["도로명"],
        row.get("소속구"),
        _to_int(row.get("AADT")),
        _to_float(row.get("불투수면")),
        lat, lon, nx, ny,
    ))


def run(csv_path: str):
    rows = read_csv(csv_path)
    conn = psycopg2.connect(**DB_CONFIG)
    ok, skipped = 0, 0
    try:
        with conn, conn.cursor() as cur:
            for row in rows:
                lat = _to_float(row.get("위도"))
                lon = _to_float(row.get("경도"))
                if lat is None or lon is None:
                    logger.warning(f"위경도 누락, 건너뜀: {row.get('도로ID')} {row.get('도로명')}")
                    skipped += 1
                    continue

                nx, ny = dfs_xy_conv(lat, lon)
                upsert_road(cur, row, lat, lon, nx, ny)
                logger.info(
                    f"적재: {row['도로ID']} {row['도로명']} ({row.get('소속구')}) -> "
                    f"lat={lat} lon={lon} nx={nx} ny={ny}"
                )
                ok += 1
        logger.info(f"완료: 적재 {ok}건, 건너뜀 {skipped}건 (총 {len(rows)}건)")
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GIS 표본 CSV(위경도 포함) road_master 적재")
    parser.add_argument("--csv", default=DEFAULT_CSV_PATH, help="CSV 파일 경로")
    args = parser.parse_args()

    try:
        run(args.csv)
    except Exception as e:
        logger.error(f"적재 실패: {e}")
        sys.exit(1)
