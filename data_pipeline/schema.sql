-- ============================================================================
-- 탄천 6PPD-Q 위험도 모니터링 프로젝트 - 초기 테이블 설계
-- 실행: psql -h $DB_HOST -U $DB_USER -d $DB_NAME -f schema.sql
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1) weather_raw : 기상청 초단기실황조회(getUltraSrtNcst) 원천 데이터
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS weather_raw (
    id              BIGSERIAL PRIMARY KEY,      -- 번호 식별자
    nx              SMALLINT NOT NULL,          -- 기상청 격자 X좌표
    ny              SMALLINT NOT NULL,          -- 기상청 격자 Y좌표
    base_date       CHAR(8)  NOT NULL,          -- API 발표일자 (YYYYMMDD)
    base_time       CHAR(4)  NOT NULL,          -- API 발표시각 (HHMM)
    obs_datetime    TIMESTAMP NOT NULL,         -- 실제 관측 시각 (base_date+base_time을 합쳐 저장)
    rn1_mm          NUMERIC(6,1),               -- 1시간 강수량(mm)
    pty_code        SMALLINT,                   -- 강수형태 코드(0:없음,1:비,2:비/눈,3:눈,4:소나기,5:빗방울,6:빗방울눈날림,7:눈날림)
    t1h_c           NUMERIC(5,1),               -- 기온(℃)
    reh_pct         NUMERIC(5,1),               -- 습도(%)
    wsd_ms          NUMERIC(5,1),               -- 풍속(m/s)
    raw_payload     JSONB,                      -- 원본 응답 전체 보관 (디버깅/재처리용)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (nx, ny, obs_datetime)
);

CREATE INDEX IF NOT EXISTS idx_weather_raw_obs_datetime ON weather_raw (obs_datetime);
CREATE INDEX IF NOT EXISTS idx_weather_raw_nx_ny ON weather_raw (nx, ny);

-- ----------------------------------------------------------------------------
-- 2) road_master : 도로 마스터 데이터
--    tancheon_week2_final.csv 컬럼(도로ID,도로명,행정동,소속구,도로연장_km,차선수,
--    AADT_대일_평일,불투수면비율_퍼센트,기준년도,출처_AADT,출처_불투수면)을 그대로 반영.
--    lat/lon/nx/ny는 geocode_and_import_road_master.py가 CSV를 적재한 "이후"
--    지오코딩으로 채우는 값이라 처음엔 NULL일 수 있음 (그래서 NOT NULL 아님).
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS road_master (
    road_id             VARCHAR(50) PRIMARY KEY,
    road_name           VARCHAR(200) NOT NULL,
    dong                VARCHAR(100),           -- 행정동 (지오코딩 입력 주소로 사용)
    gu                  VARCHAR(50),            -- 소속구
    road_length_km      NUMERIC(6,3),           -- 도로연장(km)
    lane_count          SMALLINT,               -- 차선수
    aadt                INTEGER,                -- 연평균 일교통량(AADT, 대/일)
    impervious_ratio    NUMERIC(5,2),           -- 인근 불투수면적 비율(%)
    reference_year      SMALLINT,               -- AADT/불투수면 기준년도
    source_aadt         VARCHAR(200),           -- AADT 출처
    source_impervious   VARCHAR(200),           -- 불투수면 출처
    lat                 NUMERIC(9,6),           -- 지오코딩 결과 위도
    lon                 NUMERIC(9,6),           -- 지오코딩 결과 경도
    nx                  SMALLINT,               -- 기상 격자와 조인하기 위해 계산해서 저장 (dfs_xy_conv 사용)
    ny                  SMALLINT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_road_master_nx_ny ON road_master (nx, ny);

-- ----------------------------------------------------------------------------
-- 3) dry_days_status : 선행 무강우일수(Antecedent Dry Days) 계산 결과
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dry_days_status (
    obs_date               DATE NOT NULL,
    nx                      SMALLINT NOT NULL,
    ny                      SMALLINT NOT NULL,
    daily_precip_mm         NUMERIC(6,1) NOT NULL,
    is_dry_day               BOOLEAN NOT NULL,
    antecedent_dry_days      INTEGER NOT NULL,   -- 해당 날짜까지 연속 무강우일수
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (obs_date, nx, ny)
);

-- ----------------------------------------------------------------------------
-- 4) processed_risk_log : 위험도 산식(risk_formula.py) 계산 결과
--    aadt_norm ~ runoff_index는 최종 risk_score만 남기지 않고 중간값도 같이 저장해서,
--    "왜 이 점수가 나왔는지" 나중에 디버깅/검증할 수 있게 함.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS processed_risk_log (
    id                  BIGSERIAL PRIMARY KEY,
    road_id             VARCHAR(50) REFERENCES road_master(road_id),
    calc_datetime        TIMESTAMP NOT NULL,
    rn1_mm               NUMERIC(6,1),
    antecedent_dry_days  INTEGER,
    aadt                 INTEGER,
    impervious_ratio     NUMERIC(5,2),
    aadt_norm             NUMERIC(6,4),
    dry_days_norm         NUMERIC(6,4),
    rain_trigger          NUMERIC(6,4),
    impervious_norm       NUMERIC(6,4),
    load_index             NUMERIC(6,4),
    runoff_index            NUMERIC(6,4),
    risk_score            NUMERIC(5,2),          -- 0~100
    risk_grade             VARCHAR(10),           -- 관심/주의/경계/심각 (4단계, classify_risk_grade 결과)
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (road_id, calc_datetime)
);

CREATE INDEX IF NOT EXISTS idx_processed_risk_log_calc_datetime ON processed_risk_log (calc_datetime);

-- 이미 만들어진 테이블에도 안전하게 컬럼을 추가 (CREATE TABLE IF NOT EXISTS는 기존 테이블을
-- 수정하지 않으므로, schema.sql을 다시 실행해도 risk_grade가 없으면 여기서 추가됩니다).
ALTER TABLE processed_risk_log ADD COLUMN IF NOT EXISTS risk_grade VARCHAR(10);

-- ----------------------------------------------------------------------------
-- 5) risk_alert_log : 위험도 등급이 상승(임계치 도달)한 순간을 기록하는 트리거 로그
--    (CrewAI 자동 트리거 파이프라인이 "무엇을 보고 발동했는지" 추적하기 위한 테이블)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS risk_alert_log (
    id                  BIGSERIAL PRIMARY KEY,
    road_id             VARCHAR(50) REFERENCES road_master(road_id),
    calc_datetime        TIMESTAMP NOT NULL,       -- 등급이 상승한 시점의 계산 시각 (processed_risk_log 참조)
    prev_grade           VARCHAR(10),               -- 직전 등급 (없으면 NULL = 최초 계산)
    new_grade             VARCHAR(10) NOT NULL,      -- 상승한 새 등급
    risk_score            NUMERIC(5,2) NOT NULL,
    notified               BOOLEAN NOT NULL DEFAULT false,  -- CrewAI 에이전트 호출 여부
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_risk_alert_log_road_id ON risk_alert_log (road_id);
