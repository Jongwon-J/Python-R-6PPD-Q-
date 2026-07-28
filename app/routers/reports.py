import os
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile, status
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.config import ADMIN_TOKEN, UPLOAD_DIR
from app.database import get_db
from app.models import CitizenReport
from app.schemas import ReportListItem, ReportResponse, ReportListResponse

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


@router.get("/", response_model=ReportListResponse)
def list_reports(
    limit: int = 20,
    offset: int = 0,
    status_filter: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    제보 목록 조회 (상태 필터 + 페이지네이션 지원).

    - status_filter: 'pending' | 'reviewed' | 'resolved' 중 하나로 필터링 (생략 시 전체)
    - limit/offset: 20개씩 페이지네이션
    """
    query = db.query(CitizenReport)
    if status_filter:
        query = query.filter(CitizenReport.status == status_filter)

    total = query.count()
    reports = (
        query.order_by(CitizenReport.reported_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return {
        "items": reports,
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + limit < total,
    }

VALID_STATUSES = {"pending", "reviewed", "resolved"}


class StatusUpdate(BaseModel):
    status: str


def _require_admin(x_admin_token: Optional[str]) -> None:
    """제보 상태 변경 같은 관리 작업 전에 토큰을 검증. ADMIN_TOKEN이 설정 안 됐으면 안전하게 항상 차단."""
    if not ADMIN_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="서버에 ADMIN_TOKEN이 설정되지 않아 관리 기능을 쓸 수 없습니다.",
        )
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="관리자 토큰이 올바르지 않습니다.")


@router.patch("/{report_id}/status", response_model=ReportResponse)
def update_report_status(
    report_id: int,
    payload: StatusUpdate,
    db: Session = Depends(get_db),
    x_admin_token: Optional[str] = Header(None),
):
    """제보 상태 변경 (접수 → 검토중 → 처리완료). 관리자 토큰이 있어야 허용."""
    _require_admin(x_admin_token)

    if payload.status not in VALID_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"status는 {', '.join(VALID_STATUSES)} 중 하나여야 합니다.",
        )

    report = db.query(CitizenReport).filter(CitizenReport.id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail=f"id={report_id} 제보를 찾을 수 없습니다.")

    report.status = payload.status
    db.commit()
    db.refresh(report)
    return report
    