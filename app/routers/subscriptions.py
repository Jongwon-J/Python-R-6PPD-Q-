from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app.models import Subscription
from app.schemas import SubscriptionResponse

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


class SubscriptionCreate(BaseModel):
    contact: str      # 전화번호 또는 이메일
    road_id: str       # 구독할 도로 ID


def _validate_road_exists(road_id: str, db: Session) -> None:
    """구독하려는 road_id가 실제 road_master에 있는지 확인"""
    result = db.execute(
        text("SELECT 1 FROM road_master WHERE road_id = :road_id"),
        {"road_id": road_id},
    ).first()
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"존재하지 않는 road_id입니다: {road_id}",
        )


@router.post("/", response_model=SubscriptionResponse, status_code=status.HTTP_201_CREATED)
def create_subscription(payload: SubscriptionCreate, db: Session = Depends(get_db)):
    """관심 도로 알림 구독 등록"""
    _validate_road_exists(payload.road_id, db)

    new_sub = Subscription(contact=payload.contact, road_id=payload.road_id)

    try:
        db.add(new_sub)
        db.commit()
        db.refresh(new_sub)
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 구독 중이거나 저장 중 오류가 발생했습니다.",
        )

    return new_sub


@router.get("/", response_model=List[SubscriptionResponse])
def list_subscriptions(db: Session = Depends(get_db)):
    """구독 목록 조회 (디버깅/관리자 확인용)"""
    return db.query(Subscription).all()