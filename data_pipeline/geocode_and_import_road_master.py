"""
geocode_and_import_road_master.py
tancheon_week2_final.csv(도로 마스터 원본)를 읽어, 각 도로의 "행정동" 주소를 카카오 로컬 API로
지오코딩(위경도 변환)한 뒤, 기상청 격자좌표(nx, ny)까지 계산해서 road_master 테이블에 적재합니다.

CSV 컬럼 (data/tancheon_week2_final.csv):
    도로ID,도로명,행정동,소속구,도로연장_km,차선수,AADT_대일_평일,불투수면비율_퍼센트,
    기준년도,출처_AADT,출처_불투수면

사용법:
    python geocode_and_import_road_master.py [--csv data/tancheon_week2_final.csv]
"""

import os
import csv
import sys
import math
import time
import logging
import argparse
from typing import Optional, Tuple, Dict

import requests
import psycopg2
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("geocode_and_import_road_master")

KAKAO_REST_API_KEY = os.environ["KAKAO_REST_API_KEY"]
KAKAO_GEOCODE_URL = "https://dapi.kakao.com/v2/local/search/address.json"

DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "localhost"),
    "port": os.environ.get("DB_PORT", "5432"),
    "dbname": os.environ["DB_NAME"],
    "user": os.environ["DB_USER"],
    "password": os.environ["DB_PASSWORD"],
}

DEFAULT_CSV_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "tancheon_week2_final.csv"
)


# ---------------------------------------------------------------------------
# 격자좌표 변환 (weather_collector.py의 dfs_xy_conv와 동일한 로직).
# 두 스크립트가 서로 import하지 않고 독립 실행 가능하도록 의도적으로 중복 구현함.
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


def geocode_address(address: str, retries: int = 3, backoff_sec: float = 1.0) -> Optional[Tuple[float, float]]:
    """카카오 주소 검색 API로 (lat, lon)을 반환. 결과가 없으면 None."""
    headers = {"Authorization": f"KakaoAK {KAKAO_REST_API_KEY}"}
    params = {"query": address}

    last_err: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(KAKAO_GEOCODE_URL, headers=headers, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            documents = data.get("documents", [])
            if not documents:
                logger.warning(f"지오코딩 결과 없음: {address}")
                return None
            doc = documents[0]
            lon = float(doc["x"])  # 카카오 API: x = 경도
            lat = float(doc["y"])  # 카카오 API: y = 위도
            return lat, lon
        except Exception as e:
            last_err = e
            logger.warning(f"카카오 지오코딩 실패 (시도 {attempt}/{retries}) address={address}: {e}")
            if attempt < retries:
                time.sleep(backoff_sec)

    logger.error(f"카카오 지오코딩 최종 실패: {address} ({last_err})")
    return None


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


def upsert_road(cur, row: Dict, lat: Optional[float], lon: Optional[float], nx: Optional[int], ny: Optional[int]):
    sql = """
        INSERT INTO road_master
            (road_id, road_name, dong, gu, road_length_km, lane_count, aadt, impervious_ratio,
             reference_year, source_aadt, source_impervious, lat, lon, nx, ny, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
        ON CONFLICT (road_id)
        DO UPDATE SET
            road_name = EXCLUDED.road_name,
            dong = EXCLUDED.dong,
            gu = EXCLUDED.gu,
            road_length_km = EXCLUDED.road_length_km,
            lane_count = EXCLUDED.lane_count,
            aadt = EXCLUDED.aadt,
            impervious_ratio = EXCLUDED.impervious_ratio,
            reference_year = EXCLUDED.reference_year,
            source_aadt = EXCLUDED.source_aadt,
            source_impervious = EXCLUDED.source_impervious,
            lat = EXCLUDED.lat,
            lon = EXCLUDED.lon,
            nx = EXCLUDED.nx,
            ny = EXCLUDED.ny,
            updated_at = now();
    """
    cur.execute(sql, (
        row["도로ID"],
        row["도로명"],
        row["행정동"],
        row["소속구"],
        _to_float(row.get("도로연장_km")),
        _to_int(row.get("차선수")),
        _to_int(row.get("AADT_대일_평일")),
        _to_float(row.get("불투수면비율_퍼센트")),
        _to_int(row.get("기준년도")),
        row.get("출처_AADT"),
        row.get("출처_불투수면"),
        lat, lon, nx, ny,
    ))


def run(csv_path: str):
    rows = read_csv(csv_path)
    conn = psycopg2.connect(**DB_CONFIG)
    ok, failed = 0, 0
    try:
        with conn, conn.cursor() as cur:
            for row in rows:
                address = row["행정동"]
                geocoded = geocode_address(address)
                if geocoded is None:
                    lat, lon, nx, ny = None, None, None, None
                    failed += 1
                else:
                    lat, lon = geocoded
                    nx, ny = dfs_xy_conv(lat, lon)
                    ok += 1

                upsert_road(cur, row, lat, lon, nx, ny)
                logger.info(
                    f"적재: {row['도로ID']} {row['도로명']} ({address}) -> lat={lat} lon={lon} nx={nx} ny={ny}"
                )
                time.sleep(0.2)  # 카카오 API 호출 간격 (초당 호출량 제한 대응)
        logger.info(f"완료: 성공 {ok}건, 지오코딩 실패 {failed}건 (총 {len(rows)}건)")
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="도로 마스터 CSV 지오코딩 후 적재")
    parser.add_argument("--csv", default=DEFAULT_CSV_PATH, help="CSV 파일 경로")
    args = parser.parse_args()

    try:
        run(args.csv)
    except Exception as e:
        logger.error(f"적재 실패: {e}")
        sys.exit(1)
