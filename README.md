# EcoBridge — 탄천 6PPD-Q 하천 유입 조기경보 시스템

타이어 마모 시 발생하는 독성물질 **6PPD-Q**가 강우 시 하천으로 유입되는 위험을 실시간 기상·교통·환경 데이터로 예측하고, 위험 등급이 상승하면 자동으로 행정 공문서를 생성하고 담당 공무원에게 SMS로 알리는 시스템입니다.

## 왜 이 프로젝트를 만드나

6PPD-Q는 타이어 마모 분진에서 나오는 물질로, 코호 연어를 포함한 수생 생물에게 치명적인 것으로 보고되어 있습니다(Tian et al., 2021, *Science*, LC50 0.8±0.16 μg/L(성체 기준)). 도로에 쌓이던 이 물질은 비가 오면 첫 강우(first flush) 때 하천으로 집중 유입되는데, 국내에는 아직 실측 모니터링 체계가 없습니다. 이 프로젝트는 실측 대신 공개 데이터(강수·선행 무강우일수·교통량·불투수면비율)로 위험도를 사전 추정하는 조기경보 체계를 목표로 합니다. 서울 한강 유역 5개 지류(탄천·중랑천·안양천·홍제천·성내천) 15개 도로를 파일럿 표본으로 삼았습니다.

> 이 시스템이 계산하는 "위험도"는 실측 6PPD-Q 농도가 아니라, 논문 기반 대리 지표를 조합한 시뮬레이션 지표입니다. 자세한 한계는 [알려진 한계](#알려진-한계--확인-필요-사항) 참고.

## 아키텍처

```
기상청 API(초단기실황) ──┐
                          ├─▶ PostgreSQL ──▶ 위험도 계산(risk_formula) ──▶ 등급 상승 감지
GIS 도로 표본(AADT,       │   (weather_raw, road_master,                     │
불투수면비율, 위경도)     ┘    dry_days_status, processed_risk_log,          ▼
                               risk_alert_log)                    CrewAI(Gemini) 행정공문서 생성
                                                                            │
                              FastAPI 백엔드 ◀── 대시보드(정적 HTML+Leaflet)  ├─▶ Solapi SMS(담당 공무원)
                              (/risk, /reports, /documents)                └─▶ risk_alert_log.document_text 저장
```

## 기술 스택

| 영역 | 기술 |
|---|---|
| 데이터 수집 | Python, 기상청 단기예보 조회서비스 API, 카카오 로컬 API(지오코딩 폴백) |
| 저장소 | PostgreSQL |
| 백엔드 API | FastAPI, SQLAlchemy |
| AI 에이전트 | CrewAI + Google Gemini(`gemini-3.5-flash`) |
| SMS 알림 | Solapi |
| 프론트엔드 | 정적 HTML/JS + Leaflet(지도) |
| 인프라 | Docker / docker-compose, cron |

## 시작하기 — Docker (권장)

가장 빠르게 전체 스택(DB+백엔드+프론트엔드)을 띄우는 방법입니다.

```bash
git clone https://github.com/Jongwon-J/Python-R-6PPD-Q-.git
cd Python-R-6PPD-Q-

cp .env.example .env
# .env를 열어 아래 "환경변수" 표의 값들을 채워넣기

docker compose up --build
```

- 프론트엔드 대시보드: http://localhost:8080
- 백엔드 API: http://localhost:8000 (헬스체크: `/health`)
- DB는 컨테이너 전용 볼륨을 쓰며, 로컬에 PostgreSQL이 이미 떠있어도 호스트 포트 `5433`으로 노출되어 충돌하지 않습니다(컨테이너 내부 통신은 5432 그대로).
- 데이터 수집·위험도 계산 파이프라인은 Docker에 포함되어 있지 않으므로, 아래 "데이터 파이프라인 실행"을 별도로 돌려야 대시보드에 실제 데이터가 채워집니다.

## 시작하기 — 로컬 개발 환경

### 요구 사항

- Python 3.10 이상 (CrewAI가 3.10+ 요구)
- PostgreSQL 14 이상 (로컬 설치 또는 원격 서버)
- 기상청 API 인증키 ([공공데이터포털](https://www.data.go.kr/data/15084084/openapi.do)에서 "기상청_단기예보 조회서비스" 활용신청)
- 카카오 REST API 키 ([Kakao Developers](https://developers.kakao.com), 무료 — 위경도가 없는 도로 데이터를 추가할 때만 필요)
- Google Gemini API 키 ([Google AI Studio](https://aistudio.google.com), 카드 등록 없이 무료 발급)
- Solapi API 키/시크릿 ([solapi.com](https://solapi.com), 개인 가입 가능, 발신번호 사전 등록 필요)

### 설치

```bash
git clone https://github.com/Jongwon-J/Python-R-6PPD-Q-.git
cd Python-R-6PPD-Q-

python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install -r data_pipeline/requirements.txt
pip install -r app/requirements.txt

cp .env.example .env
# .env를 열어 아래 "환경변수" 표의 값들을 채워넣기
```

### DB 스키마 적용

```bash
psql -U postgres -d tancheon_risk -f data_pipeline/schema.sql
```
(`schema.sql`은 `CREATE TABLE IF NOT EXISTS` + `ADD COLUMN IF NOT EXISTS` 패턴으로 작성되어 있어, 이미 만들어진 DB에 다시 실행해도 기존 데이터를 지우지 않고 안전하게 최신 스키마로 맞춰줍니다.)

### 도로 표본 적재

GIS 검증을 거쳐 위경도가 이미 있는 표본(`data_pipeline/gis_mapping_data.csv`)을 쓰는 경우:
```bash
python data_pipeline/import_gis_road_master.py
```
주소만 있고 위경도가 없는 데이터를 추가하는 경우(카카오 지오코딩 폴백):
```bash
python data_pipeline/geocode_and_import_road_master.py
```

### 데이터 파이프라인 실행

```bash
python data_pipeline/weather_collector.py    # 실시간 강수량 수집
python data_pipeline/etl_risk_pipeline.py    # 위험도 계산 + 등급 상승 감지
python data_pipeline/crew_alert_agent.py     # 등급 상승 시 공문서 생성 + SMS 발송
```

정상 동작이 확인되면 `data_pipeline/run_pipeline.sh`를 만들어 cron에 10분 주기로 등록합니다.
```cron
*/10 * * * * /path/to/project/data_pipeline/run_pipeline.sh >> /path/to/project/data_pipeline/pipeline.log 2>&1
```
> macOS에서는 cron이 Desktop/Documents/Downloads 폴더에 접근할 때 시스템 개인정보 보호 정책(TCC)에 막힐 수 있습니다. 이 경우 시스템 설정 > 개인정보 보호 및 보안 > 전체 디스크 접근 권한에 `/usr/sbin/cron`을 추가해야 합니다.

### 백엔드 API 실행

```bash
uvicorn app.main:app --reload --port 8000
```

### 프론트엔드 실행

```bash
cd frontend
python3 -m http.server 8080
```
브라우저에서 http://localhost:8080 접속.

## 환경변수

| 변수명 | 설명 |
|---|---|
| `KMA_SERVICE_KEY` | 기상청 API 인증키 (Decoding 키 사용) |
| `KAKAO_REST_API_KEY` | 카카오 로컬 API REST 키 (주소 기반 도로 지오코딩용, 선택) |
| `DB_HOST` / `DB_PORT` / `DB_NAME` / `DB_USER` / `DB_PASSWORD` | PostgreSQL 접속 정보 |
| `TANCHEON_TARGET_POINT` / `TANCHEON_NX` / `TANCHEON_NY` | road_master가 비어있을 때 쓰는 기본 관측 지점(폴백) |
| `DRY_DAY_THRESHOLD_MM` | 무강우 판정 기준 강수량(mm/day) |
| `GEMINI_API_KEY` | CrewAI가 호출하는 Google Gemini API 키 |
| `SOLAPI_API_KEY` / `SOLAPI_API_SECRET` | Solapi API 인증 정보 |
| `SOLAPI_FROM_NUMBER` | Solapi에 등록한 발신번호 |
| `SOLAPI_TO_NUMBER` | 등급 상승 알림을 받을 담당 공무원 번호 |
| `UPLOAD_DIR` | 시민 제보 이미지 저장 경로 (기본 `uploads/reports`) |
| `ADMIN_TOKEN` | 시민 제보 상태 변경(관리자 기능) 인증 토큰. 비워두면 관리 기능이 항상 차단됨(fail-safe) |

## 위험도 산출 공식

```
부하지수 = 0.6 × AADT_정규화 + 0.4 × 건조일수_정규화
유출지수 = 0.7 × 강수트리거 + 0.3 × 불투수면_정규화
위험도(0~100) = 부하지수 × 유출지수 × 100
```

강수가 없으면 위험도가 0에 수렴하도록 덧셈이 아닌 곱셈 구조로 설계했습니다. AADT·불투수면비율은 절대 스케일이 아니라 표본 내 상대(min-max) 정규화를 씁니다. 가중치(0.6/0.4, 0.7/0.3)는 King & Rodgers(2025)·Halama et al.(2024) 등 개별 변수 논문에서 확인된 상대적 영향력을 근거로 삼은 방향성 근사값이며, 정밀 회귀계수가 아닙니다.

### 위험도 등급 (4단계)

| 등급 | 위험도 범위 | 근거 |
|---|---|---|
| 관심 | 0 ~ 33.5 | 표본(n=15) 사분위수 하위 25% |
| 주의 | 33.5 ~ 40.5 | 25~50% |
| 경계 | 40.5 ~ 49.9 | 50~75% |
| 심각 | 49.9 초과 | 상위 25% |

4단계 체계는 「재난 및 안전관리 기본법」 제38조(위기경보의 발령)와 대응되도록 설계했으며, 경계값 자체는 현재 표본(n=15) 위험도 분포의 사분위수(quartile)를 기준으로 산정한 상대치입니다. 절대적인 위해성 기준이 아니라 표본 내 상대적 위치를 나타내는 분류이므로, 표본이 확대되면 재산정이 필요합니다.

## 주요 API 엔드포인트

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/risk/roads` | 도로별 최신 위험도 점수·등급 조회 |
| GET | `/reports/` | 시민 제보 목록 (상태 필터·페이지네이션) |
| POST | `/reports/` | 시민 제보 등록 (위경도·설명·사진) |
| PATCH | `/reports/{id}/status` | 제보 상태 변경 (관리자 토큰 필요) |
| GET | `/documents/` | 생성된 경보 공문서 목록 |
| GET | `/documents/latest` | 가장 최근 공문서 |
| GET | `/documents/{id}/download` | 공문서 다운로드(.txt) |
| GET | `/health` | 헬스체크 |

## 알려진 한계 / 확인 필요 사항

- 위험도는 실측 6PPD-Q 농도가 아니라 시뮬레이션 기반 대리 지표이며, 국내 실측 데이터로 검증된 적이 없습니다.
- 위험도 산식의 가중치(0.6/0.4, 0.7/0.3)는 소표본(n=4) 문헌 기반 방향성 근사값으로, 정밀 회귀계수가 아닙니다.
- 위험도 등급 경계값(33.5/40.5/49.9)은 현재 표본(n=15)의 상대적 분포이며, 절대적 안전 기준이 아닙니다. 표본 확대 시 재산정이 필요합니다.
- 담당 공무원 SMS 알림은 국가재난안전통신망(긴급재난문자/CBS)과 무관한 부서 내부 알림이며, 이를 대체하지 않습니다.
- 기상 데이터는 기상청 5km 격자 단위로 수집되어, 같은 격자 안에 있는 서로 다른 도로들은 동일한 강수값을 공유합니다. 국지적 강우 편차는 반영하지 못합니다.

## 참고 자료

- Tian et al., 2021, *Science* — 6PPD-Q 코호 연어 급성 독성(LC50) 최초 규명
- King & Rodgers, 2025 — 강우 발생 후 6PPD-Q 하천 농도 급상승(first flush) 실측
- Halama et al., 2024 — 선행 건조일수(ADD)에 따른 6PPD-Q 농도 변화
- Helm et al., 2024 — 도로밀도(불투수면 프록시)에 따른 6PPD-Q 농도 차이
- [기상청_단기예보 조회서비스 (공공데이터포털)](https://www.data.go.kr/data/15084084/openapi.do)
- [격자좌표 변환 로직(LCC DFS)](https://gist.github.com/fronteer-kr/14d7f779d52a21ac2f16)
- [카카오 로컬 API 개발 가이드](https://developers.kakao.com/docs/latest/ko/local/dev-guide)