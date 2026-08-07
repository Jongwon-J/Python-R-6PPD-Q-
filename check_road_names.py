import os
import requests
from dotenv import load_dotenv

load_dotenv()
KAKAO_KEY = os.getenv("KAKAO_REST_API_KEY")

points = {
    "8903073 (양천구)": (126.8339, 37.5228),
    "8903318 (영등포구)": (126.8965, 37.5280),
}

for name, (lon, lat) in points.items():
    url = "https://dapi.kakao.com/v2/local/geo/coord2address.json"
    headers = {"Authorization": f"KakaoAK {KAKAO_KEY}"}
    params = {"x": lon, "y": lat}
    res = requests.get(url, headers=headers, params=params)
    print(name, "->", res.json())