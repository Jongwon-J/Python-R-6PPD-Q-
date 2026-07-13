from typing import List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db

router = APIRouter(prefix="/risk", tags=["risk"])


@router.get("/roads")
def get_latest_risk_by_road(db: Session = Depends(get_db)):
    """
    도로별 가장 최근 위험도 점수 조회.
    processed_risk_log에서 road_id마다 가장 최신 calc_datetime 행만 골라서,
    road_master의 이름/위치 정보와 함께 반환.
    """
    query = text("""
        SELECT
            r.road_id,
            rm.road_name,
            rm.lat,
            rm.lon,
            r.risk_score,
            r.calc_datetime
        FROM processed_risk_log r
        JOIN road_master rm ON rm.road_id = r.road_id
        WHERE r.calc_datetime = (
            SELECT MAX(r2.calc_datetime)
            FROM processed_risk_log r2
            WHERE r2.road_id = r.road_id
        )
        ORDER BY r.risk_score DESC
    """)

    rows = db.execute(query).mappings().all()
    return [dict(row) for row in rows]