"""
weather_collector.py - 실시간 강수량 수집기
기상청 단기예보 조회서비스 - 초단기실황조회(getUltraSrtNcst) API 연동
탄천 유역 실시간 시간당 강수량(RN1) 등을 수집하여 PostgreSQL weather_raw 테이블에 적재합니다.

API 문서: 공공데이터포털 "기상청_단기예보 조회서비스"
Endpoint: https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getUltraSrtNcst

"""

import os # 환경변수 읽을 때 사용
import sys
import json
import time
import math
import logging # 로그 남기기
from datetime import datetime, timedelta
from typing import Optional, Tuple, Dict

import requests # 외부 API에 HTTP 요청 보내기
import psycopg2 # python에서 PostgreSQL과 통신
from dotenv import load_dotenv # .env 파일 내용 읽어서 환경 변수로 등록

# .env 파일에 있는 비밀번호, 인증키들을 기억장치에 등록
load_dotenv()

# "로그를 어떤 모양으로 찍을지" 설정
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("weather_collector")

# ---------------------------------------------------------------------------
# 설정
# ---------------------------------------------------------------------------
SERVICE_KEY = os.environ["KMA_SERVICE_KEY"]
API_URL = "https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getUltraSrtNcst"

# 탄천 유역 후보 관측 지점 (좌표는 대략치 — 5km 격자 특성상 인근 지점은 같은 격자로 매핑됨).
# 실제 연구 대상 구간이 확정되면 좌표를 조정하고 dfs_xy_conv()로 nx,ny를 다시 계산하세요.
TANCHEON_POINTS = {
    "upstream":   {"lat": 37.2478, "lon": 127.1146, "nx": 62, "ny": 120},  # 용인시 기흥구 마북동 인근
    "midstream":  {"lat": 37.3826, "lon": 127.1188, "nx": 62, "ny": 123},  # 성남시 분당구청 인근
    "downstream": {"lat": 37.5036, "lon": 127.1130, "nx": 62, "ny": 125},  # 강남구 대치동~송파구 삼전동 경계(한강 합류부)
}
TARGET_POINT = os.environ.get("TANCHEON_TARGET_POINT", "midstream")

# DB 접속 정보
DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "localhost"),
    "port": os.environ.get("DB_PORT", "5432"),
    "dbname": os.environ["DB_NAME"],
    "user": os.environ["DB_USER"],
    "password": os.environ["DB_PASSWORD"],
}

# 위,경도 -> 기상청 LCC DFS 격자좌표(nx, ny) 변환하는 함수
def dfs_xy_conv(lat: float, lon: float) -> Tuple[int, int]: # 격좌좌표 변환 함수
    
    RE = 6371.00877     # 지구 반경(km)
    GRID = 5.0            # 격자 간격(km)
    SLAT1, SLAT2 = 30.0, 60.0    # 투영 위도 1, 2 (degree)
    OLON, OLAT = 126.0, 38.0      # 기준점 경도, 위도 (degree)
    XO, YO = 43, 136                # 기준점 X, Y좌표 (GRID)

    DEGRAD = math.pi / 180.0
    re = RE / GRID
    slat1, slat2 = SLAT1 * DEGRAD, SLAT2 * DEGRAD
    olon, olat = OLON * DEGRAD, OLAT * DEGRAD

    # 원뿔도법(원추도법) 지도 투영에 쓰이는 중간 계산값
    # 지도를 평면에 펼 때 왜곡을 보정하는 계산
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

# API에 물어볼 시각 계산하는 함수
def get_base_datetime(now: Optional[datetime] = None) -> Tuple[str, str, datetime]:

    now = now or datetime.now()
    # 지금 분이 10분 미만 -> 1시간 빼기 else 그대로 두기
    base_dt = now - timedelta(hours=1) if now.minute < 10 else now
    base_dt = base_dt.replace(minute=0, second=0, microsecond=0)
    return base_dt.strftime("%Y%m%d"), base_dt.strftime("%H%M"), base_dt

# 초단기실황조회 API 호출하는 함수
def fetch_ultra_srt_ncst(nx: int, ny: int, base_date: str, base_time: str,
                          retries: int = 3, backoff_sec: float = 2.0) -> Dict[str, str]:
    
    params = {
        "serviceKey": SERVICE_KEY,
        "pageNo": "1",
        "numOfRows": "10",
        "dataType": "JSON",
        "base_date": base_date,
        "base_time": base_time,
        "nx": nx,
        "ny": ny,
    }

    last_err: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(API_URL, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            header = data["response"]["header"]
            if header["resultCode"] != "00":
                raise RuntimeError(f"KMA API error: {header['resultCode']} {header['resultMsg']}")

            items = data["response"]["body"]["items"]["item"]
            return {item["category"]: item["obsrValue"] for item in items}
        except Exception as e:
            last_err = e
            logger.warning(f"API 호출 실패 (시도 {attempt}/{retries}): {e}")
            if attempt < retries:
                time.sleep(backoff_sec)

    raise RuntimeError(f"초단기실황조회 API 호출 최종 실패: {last_err}")


def _to_float(v, default=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def save_to_db(nx: int, ny: int, base_date: str, base_time: str, obs_dt: datetime, values: Dict[str, str]):
    """weather_raw 테이블에 적재. 동일 (nx, ny, obs_datetime) 재수집 시 UPSERT."""
    rn1_mm = _to_float(values.get("RN1"), default=0.0)

    sql = """
        INSERT INTO weather_raw
            (nx, ny, base_date, base_time, obs_datetime, rn1_mm, pty_code, t1h_c, reh_pct, wsd_ms, raw_payload)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (nx, ny, obs_datetime)
        DO UPDATE SET
            rn1_mm = EXCLUDED.rn1_mm,
            pty_code = EXCLUDED.pty_code,
            t1h_c = EXCLUDED.t1h_c,
            reh_pct = EXCLUDED.reh_pct,
            wsd_ms = EXCLUDED.wsd_ms,
            raw_payload = EXCLUDED.raw_payload;
    """
    conn = psycopg2.connect(**DB_CONFIG) # DB에 연결
    try:
        with conn, conn.cursor() as cur:
            cur.execute(sql, (
                nx, ny, base_date, base_time, obs_dt,
                rn1_mm,
                int(_to_float(values.get("PTY"), default=0)),
                _to_float(values.get("T1H")),
                _to_float(values.get("REH")),
                _to_float(values.get("WSD")),
                json.dumps(values, ensure_ascii=False),
            ))
        logger.info(f"저장 완료: {obs_dt} nx={nx} ny={ny} RN1={rn1_mm}mm PTY={values.get('PTY')}")
    finally:
        conn.close()


def run():
    if TARGET_POINT not in TANCHEON_POINTS:
        raise ValueError(f"알 수 없는 TANCHEON_TARGET_POINT: {TARGET_POINT}")

    point = TANCHEON_POINTS[TARGET_POINT]
    nx, ny = point["nx"], point["ny"]

    base_date, base_time, obs_dt = get_base_datetime()
    logger.info(f"조회 시작: point={TARGET_POINT} base_date={base_date} base_time={base_time} nx={nx} ny={ny}")

    values = fetch_ultra_srt_ncst(nx, ny, base_date, base_time)
    save_to_db(nx, ny, base_date, base_time, obs_dt, values)


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        logger.error(f"수집 실패: {e}")
        sys.exit(1)
