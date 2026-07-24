from typing import List, Optional
from urllib.parse import quote
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy import text
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db

router = APIRouter(prefix="/documents", tags=["documents"])


class DocumentSummary(BaseModel):
    id: int
    road_name: str
    gu: Optional[str] = None
    new_grade: str
    risk_score: float
    created_at: datetime


class DocumentDetail(DocumentSummary):
    document_text: str


def _row_to_dict(row) -> dict:
    return dict(row._mapping)


@router.get("/", response_model=List[DocumentSummary])
def list_documents(limit: int = 20, db: Session = Depends(get_db)):
    rows = db.execute(
        text("""
            SELECT a.id, r.road_name, r.gu, a.new_grade, a.risk_score, a.created_at
            FROM risk_alert_log a
            JOIN road_master r ON r.road_id = a.road_id
            WHERE a.document_text IS NOT NULL
            ORDER BY a.created_at DESC
            LIMIT :limit
        """),
        {"limit": limit},
    ).all()
    return [_row_to_dict(r) for r in rows]


@router.get("/latest", response_model=DocumentDetail)
def get_latest_document(db: Session = Depends(get_db)):
    row = db.execute(
        text("""
            SELECT a.id, r.road_name, r.gu, a.new_grade, a.risk_score, a.created_at, a.document_text
            FROM risk_alert_log a
            JOIN road_master r ON r.road_id = a.road_id
            WHERE a.document_text IS NOT NULL
            ORDER BY a.created_at DESC
            LIMIT 1
        """)
    ).first()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="아직 생성된 경보 문서가 없습니다. 위험도 등급이 상승하면 자동으로 생성돼요.",
        )
    return _row_to_dict(row)


@router.get("/{alert_id}/download")
def download_document(alert_id: int, db: Session = Depends(get_db)):
    row = db.execute(
        text("""
            SELECT a.id, r.road_name, a.new_grade, a.created_at, a.document_text
            FROM risk_alert_log a
            JOIN road_master r ON r.road_id = a.road_id
            WHERE a.id = :alert_id AND a.document_text IS NOT NULL
        """),
        {"alert_id": alert_id},
    ).first()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"id={alert_id} 문서를 찾을 수 없습니다.",
        )

    data = _row_to_dict(row)
    filename = f"6PPDQ_경보문서_{data['road_name']}_{data['new_grade']}_{data['id']}.txt"
    ascii_fallback = f"6PPDQ_report_{data['id']}.txt"
    encoded_filename = quote(filename)

    return Response(
        content=data["document_text"],
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{ascii_fallback}"; '
                f"filename*=UTF-8''{encoded_filename}"
            )
        },
    )