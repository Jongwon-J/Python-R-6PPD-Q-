from fastapi import APIRouter

router = APIRouter(prefix="/traffic", tags=["traffic"])

@router.get("/")
def get_traffic_data():
    # TODO: 실제 Linkflow(또는 공공데이터포털) API 연동 후 이 부분 교체 예정
    mock_data = {
        "location": "탄천 인근 도로",
        "aadt": 12500,          # 일평균 교통량 (예시 값)
        "timestamp": "2026-07-03T10:00:00",
        "source": "mock_data"   # 실제 연동 전까지는 mock 표시
    }
    return mock_data