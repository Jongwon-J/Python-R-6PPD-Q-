from sqlalchemy import Column, BigInteger, Numeric, Text, String, DateTime
from sqlalchemy.sql import func

from app.database import Base


class CitizenReport(Base):
    __tablename__ = "citizen_reports"

    id = Column(BigInteger, primary_key=True, index=True)
    lat = Column(Numeric(9, 6), nullable=False)
    lon = Column(Numeric(9, 6), nullable=False)
    description = Column(Text, nullable=True)
    image_path = Column(String(500), nullable=True)
    road_id = Column(String(50), nullable=True)
    status = Column(String(20), nullable=False, default="pending")
    reported_at = Column(DateTime(timezone=True), server_default=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(BigInteger, primary_key=True, index=True)
    contact = Column(String(100), nullable=False)
    road_id = Column(String(50), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())