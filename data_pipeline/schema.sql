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
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS road_master (
    road_id             VARCHAR(50) PRIMARY KEY,
    road_name           VARCHAR(200),
    lat                 NUMERIC(9,6) NOT NULL,
    lon                 NUMERIC(9,6) NOT NULL,
    nx                  SMALLINT,               -- 기상 격자와 조인하기 위해 미리 계산해서 저장 (dfs_xy_conv 사용)
    ny                  SMALLINT,
    aadt                INTEGER,                -- 연평균 일교통량(AADT)
    impervious_ratio    NUMERIC(5,2),           -- 인근 불투수면적 비율(%)
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
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
-- 4) processed_risk_log : 3주차에 채워질 최종 위험도 테이블
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS processed_risk_log (
    id                  BIGSERIAL PRIMARY KEY,
    road_id             VARCHAR(50) REFERENCES road_master(road_id),
    calc_datetime        TIMESTAMP NOT NULL,
    rn1_mm               NUMERIC(6,1),
    antecedent_dry_days  INTEGER,
    aadt                 INTEGER,
    impervious_ratio     NUMERIC(5,2),
    risk_score            NUMERIC(5,2),          -- 0~100
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_processed_risk_log_calc_datetime ON processed_risk_log (calc_datetime);
