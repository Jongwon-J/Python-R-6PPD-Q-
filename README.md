# EcoBridge — 탄천 6PPD-Q 실시간 위험도 모니터링 시스템

타이어 마모 시 발생하는 독성물질 **6PPD-Q**가 강우 시 탄천으로 유입되는 위험을 실시간 기상·교통·환경 데이터로 예측하고, 위험 시 자동으로 행정 보고서와 재난 알림을 생성하는 시스템입니다.

## 왜 이 프로젝트를 만드나

6PPD-Q는 타이어 마모 분진에서 나오는 물질로, 코호 연어를 포함한 수생 생물에게 치명적인 것으로 보고되어 있습니다(Tian et al., 2021, *Science*). 도로에서 쌓이던 이 물질은 비가 오면 첫 강우(first flush) 때 하천으로 집중 유입되는데, 이 시점을 사전에 예측해서 지자체와 시민에게 미리 알리는 것이 이 프로젝트의 목표입니다. 서울 탄천(강남·서초 구간)을 파일럿 대상으로, 실시간 강수량·선행 무강우일수·교통량(AADT)·불투수면적비율 4개 변수를 조합한 위험도 점수(0~100)를 계산합니다.

## 아키텍처

```
기상청 API (초단기실황) ──┐
                          ├─▶ PostgreSQL ──▶ 위험도 계산(risk_formula) ──▶ CrewAI 행정보고서/알림
도로 마스터 CSV(AADT,     │        (weather_raw, road_master,              (예정: 4~5주차)
불투수면비율) + 카카오    ┘         dry_days_status, processed_risk_log)
로컬 API(지오코딩)
```

## 기술 스택

| 영역 | 기술 |
|---|---|
| 데이터 수집 | Python, 기상청 단기예보 조회서비스 API, 카카오 로컬 API |
| 저장소 | PostgreSQL |
| 백엔드 | FastAPI |
| AI 에이전트 | CrewAI |
| 시각화 | R (GIS 매핑) |
| 인프라 | Docker / docker-compose |

## 시작하기

### 요구 사항

- Python 3.11 이상
- PostgreSQL 14 이상 (로컬 설치 또는 원격 서버)
- 기상청 API 인증키 ([공공데이터포털](https://www.data.go.kr/data/15084084/openapi.do)에서 "기상청_단기예보 조회서비스" 활용신청)
- 카카오 REST API 키 ([Kakao Developers](https://developers.kakao.com)에서 애플리케이션 생성 후 발급, 무료)

### 설치

```bash
git clone https://github.com/Jongwon-J/Python-R-6PPD-Q-.git
cd Python-R-6PPD-Q-

python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env
# .env를 열어 KMA_SERVICE_KEY, KAKAO_REST_API_KEY, DB_* 값을 채워넣기
```

### 실행

```bash
python init_db.py                          # 1) PostgreSQL 테이블 생성
python weather_collector.py                # 2) 강수량 1회 수집 테스트
python dry_days_logic.py backfill          # 3) 누적 데이터로 무강우일수 계산
python geocode_and_import_road_master.py   # 4) 도로 마스터 CSV 지오코딩 후 적재
python risk_formula.py                     # 5) 위험도 산식 자체 테스트
```

정상 동작이 확인되면 실시간 수집을 위해 cron에 등록합니다.

```cron
*/10 * * * * cd /path/to/project && venv/bin/python weather_collector.py >> logs/weather.log 2>&1
10 0 * * *   cd /path/to/project && venv/bin/python dry_days_logic.py daily >> logs/dry_days.log 2>&1
```

### 환경변수

| 변수명 | 설명 | 기본값 |
|---|---|---|
| `KMA_SERVICE_KEY` | 기상청 API 인증키 (Decoding 키 사용) | - |
| `KAKAO_REST_API_KEY` | 카카오 로컬 API REST 키 (도로 지오코딩용) | - |
| `DB_HOST` / `DB_PORT` | PostgreSQL 접속 주소/포트 | `localhost` / `5432` |
| `DB_NAME` / `DB_USER` / `DB_PASSWORD` | PostgreSQL 접속 정보 | - |
| `TANCHEON_TARGET_POINT` | 강수량 수집 지점 (`upstream`/`midstream`/`downstream`) | `midstream` |
| `TANCHEON_NX` / `TANCHEON_NY` | 무강우일수 계산 기준 격자좌표 | `62` / `123` |
| `DRY_DAY_THRESHOLD_MM` | 무강우 판정 기준 강수량(mm/day) | `1.0` |

## 위험도 산출 공식

```
부하지수 = 0.6 × AADT_정규화 + 0.4 × 건조일수_정규화
유출지수 = 0.7 × 강수트리거 + 0.3 × 불투수면_정규화
위험도(0~100) = 부하지수 × 유출지수 × 100
```

강수가 없으면 위험도가 0에 수렴하도록 덧셈이 아닌 곱셈 구조로 설계했습니다. 가중치(0.6/0.4, 0.7/0.3)는 King & Rodgers(2025) 강우 이벤트 4건(n=4) 관측에 기반한 방향성 근사값으로, 정밀 회귀계수가 아닙니다 — 표본 확장 전까지는 참고치로 다뤄야 합니다. 자세한 정규화 방법은 `risk_formula.py` 주석을 참고하세요.

## 개발 로드맵

- [x] **1주차** — 팀 구성, 데이터 소스 및 위험도 변수 확정
- [x] **2주차** — 기상청 API 실시간 수집, 선행 무강우일수 알고리즘, PostgreSQL 스키마, 도로 마스터 지오코딩, 위험도 산식 구현
- [ ] **3주차** — Spatio-temporal Join ETL 파이프라인, 위험도 자동 계산 배치, 시민 제보 API
- [ ] **4주차** — CrewAI 멀티 에이전트, 실시간 위험도 서빙 API
- [ ] **5주차** — 비동기 알림(SMS) 서비스, AI 행정보고서 PDF 자동 생성
- [ ] **6주차** — Docker 컨테이너화, 부하 테스트
- [ ] **7주차** — 오픈소스 정식 릴리즈, 최종 발표

## 알려진 한계 / 확인 필요 사항

- **관측 지점 좌표**: `weather_collector.py`의 `TANCHEON_POINTS`는 탄천 상/중/하류의 대략적 좌표입니다. 연구 대상 구간이 확정되면 정확한 위경도로 교체가 필요합니다.
- **무강우 기준치**: 현재 1.0mm/day는 잠정값입니다. 6PPD-Q 논문 기반 모델에서 정식 임계값이 확정되는 대로 교체 예정입니다.
- **도로 좌표 정확도**: 도로 CSV에 위경도가 없어 행정동 단위로 지오코딩합니다. 행정동 대표 좌표라 도로의 정확한 물리적 위치와는 오차가 있을 수 있습니다.
- **강수 트리거 로직**: "비가 전혀 안 오는 상태"의 값은 원 자료에 명시되지 않아 산식 설계 의도에 따라 0으로 해석해 구현했습니다(검증 필요).
- 가중치(0.6/0.4, 0.7/0.3)는 표본 수(n=4)가 작아 확정치가 아닌 근사값입니다.

## 참고 자료

- [기상청_단기예보 조회서비스 (공공데이터포털)](https://www.data.go.kr/data/15084084/openapi.do)
- [격자좌표 변환 로직(LCC DFS)](https://gist.github.com/fronteer-kr/14d7f779d52a21ac2f16)
- [카카오 로컬 API 개발 가이드](https://developers.kakao.com/docs/latest/ko/local/dev-guide)
- Tian et al., 2021, *Science* — 6PPD-Q 코호 연어 급성 독성(LC50) 연구