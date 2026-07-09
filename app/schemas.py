from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class ReportResponse(BaseModel):
    """제보 생성 후 클라이언트에게 돌려줄 응답 형태"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    lat: float
    lon: float
    description: Optional[str] = None
    image_path: Optional[str] = None
    status: str
    reported_at: datetime


class ReportListItem(BaseModel):
    """제보 목록 조회용"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    lat: float
    lon: float
    description: Optional[str] = None
    status: str
    reported_at: datetime