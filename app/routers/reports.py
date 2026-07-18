import os
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.config import UPLOAD_DIR
from app.database import get_db
from app.models import CitizenReport
from app.schemas import ReportListItem, ReportResponse

router = APIRouter(prefix="/reports", tags=["reports"])

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_IMAGE_SIZE_BYTES = 5 * 1024 * 1024  # 5MB


def _validate_coordinates(lat: float, lon: float) -> None:
    """대한민국 영역 기준 위경도 검증"""
    if not (33.0 <= lat <= 43.0):
        raise HTTPException(
            status_code=422,
            detail="lat 값이 대한민국 영역을 벗어났습니다 (33.0 ~ 43.0 범위여야 함).",
        )
    if not (124.0 <= lon <= 132.0):
        raise HTTPException(
            status_code=422,
            detail="lon 값이 대한민국 영역을 벗어났습니다 (124.0 ~ 132.0 범위여야 함).",
        )


def _save_image(image: UploadFile) -> str:
    """업로드된 이미지를 로컬 디스크에 저장"""
    if image.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"지원하지 않는 이미지 형식입니다: {image.content_type}",
        )

    os.makedirs(UPLOAD_DIR, exist_ok=True)

    ext = os.path.splitext(image.filename or "")[1] or ".jpg"
    unique_name = f"{uuid.uuid4().hex}{ext}"
    save_path = os.path.join(UPLOAD_DIR, unique_name)

    contents = image.file.read()
    if len(contents) > MAX_IMAGE_SIZE_BYTES:
        raise HTTPException(status_code=422, detail="이미지 용량이 5MB를 초과합니다.")

    with open(save_path, "wb") as f:
        f.write(contents)

    return save_path


@router.post("/", response_model=ReportResponse, status_code=status.HTTP_201_CREATED)
def create_report(
    lat: float = Form(...),
    lon: float = Form(...),
    description: Optional[str] = Form(None),
    image: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
):
    """시민 제보 생성"""
    _validate_coordinates(lat, lon)

    image_path = None
    if image is not None and image.filename:
        image_path = _save_image(image)

    new_report = CitizenReport(
        lat=lat,
        lon=lon,
        description=description,
        image_path=image_path,
        status="pending",
    )

    try:
        db.add(new_report)
        db.commit()
        db.refresh(new_report)
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="제보 저장 중 오류가 발생했습니다.")

    return new_report


@router.get("/", response_model=List[ReportListItem])
def list_reports(limit: int = 20, db: Session = Depends(get_db)):
    """최근 제보 목록 조회 (디버깅/관리자 확인용)"""
    reports = (
        db.query(CitizenReport)
        .order_by(CitizenReport.reported_at.desc())
        .limit(limit)
        .all()
    )
    return reports