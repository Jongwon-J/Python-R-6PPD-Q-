"""
risk_formula.py - 6PPD-Q 위험도 산출 공식 구현

산식:
    부하지수(load_index)   = 0.6 * AADT_정규화 + 0.4 * 건조일수_정규화
    유출지수(runoff_index) = 0.7 * 강수트리거 + 0.3 * 불투수면_정규화
    위험도(risk_score, 0~100) = 부하지수 * 유출지수 * 100

    덧셈이 아니라 곱셈인 이유: 강수가 없으면(유출지수≈0) 교통량이 아무리 높아도
    위험도가 0에 수렴해야 하기 때문.
"""

from typing import Optional


def normalize_aadt(aadt: float, sample_min: float, sample_max: float) -> float:
    """
    AADT를 표본 내 min-max로 0~1 정규화. (값-표본min)/(표본max-표본min)
    sample_min/sample_max는 그때그때 road_master 표본에서 구해야 하는 값이라 인자로 받습니다
    (예: SELECT MIN(aadt), MAX(aadt) FROM road_master).
    """
    if sample_max <= sample_min:
        return 0.0
    value = (aadt - sample_min) / (sample_max - sample_min)
    return max(0.0, min(1.0, value))


def normalize_dry_days(antecedent_dry_days: int, cap_days: int = 7) -> float:
    """건조일수(ADD)를 0~1 정규화: (ADD-0)/(7-0). cap_days(기본 7일) 넘으면 1.0으로 캡."""
    value = antecedent_dry_days / cap_days
    return max(0.0, min(1.0, value))


def normalize_impervious(impervious_ratio_pct: float) -> float:
    """불투수면비율(%, 0~100)을 0~1 정규화: (값-0)/(100-0). 자치구 단위 값을 그대로 사용."""
    value = impervious_ratio_pct / 100.0
    return max(0.0, min(1.0, value))


def rainfall_trigger(
    is_raining: bool,
    cumulative_mm_since_rain_start: float = 0.0,
    hours_since_rain_start: float = 0.0,
    trigger_window_hours: float = 8.0,
    trigger_min_mm: float = 3.0,
    partial_value: float = 0.25,
) -> float:
    """
    강수 강도 지수.
      - 비가 전혀 안 오는 상태               -> 0.0   ("강수 없으면 유출지수≈0" 근거)
      - 강우 시작 후 trigger_window_hours(기본 8h) 이내에
        누적 trigger_min_mm(기본 3mm) 이상 도달 -> 1.0
      - 비가 오지만 위 조건 미달              -> 0.2~0.3 (기본값 0.25)
    """
    if not is_raining:
        return 0.0
    if hours_since_rain_start <= trigger_window_hours and cumulative_mm_since_rain_start >= trigger_min_mm:
        return 1.0
    return partial_value


def calculate_load_index(aadt_norm: float, dry_days_norm: float) -> float:
    """부하지수 = 0.6 * AADT_정규화 + 0.4 * 건조일수_정규화"""
    return 0.6 * aadt_norm + 0.4 * dry_days_norm


def calculate_runoff_index(rain_trigger: float, impervious_norm: float) -> float:
    """유출지수 = 0.7 * 강수트리거 + 0.3 * 불투수면_정규화"""
    return 0.7 * rain_trigger + 0.3 * impervious_norm


def calculate_risk_score(load_index: float, runoff_index: float) -> float:
    """위험도(0~100) = 부하지수 * 유출지수 * 100"""
    return round(load_index * runoff_index * 100, 2)


def calculate_full_risk(
    aadt: float,
    aadt_sample_min: float,
    aadt_sample_max: float,
    antecedent_dry_days: int,
    is_raining: bool,
    impervious_ratio_pct: float,
    cumulative_mm_since_rain_start: float = 0.0,
    hours_since_rain_start: float = 0.0,
) -> dict:
    """
    입력 원자값들로부터 정규화 -> 부하지수/유출지수 -> 최종 위험도까지 한 번에 계산.
    중간값도 함께 반환해서, processed_risk_log에 그대로 저장하거나 디버깅할 때 쓸 수 있게 했습니다.
    """
    aadt_norm = normalize_aadt(aadt, aadt_sample_min, aadt_sample_max)
    dry_days_norm = normalize_dry_days(antecedent_dry_days)
    rain_trigger_value = rainfall_trigger(is_raining, cumulative_mm_since_rain_start, hours_since_rain_start)
    impervious_norm = normalize_impervious(impervious_ratio_pct)

    load_index = calculate_load_index(aadt_norm, dry_days_norm)
    runoff_index = calculate_runoff_index(rain_trigger_value, impervious_norm)
    risk_score = calculate_risk_score(load_index, runoff_index)

    return {
        "aadt_norm": round(aadt_norm, 4),
        "dry_days_norm": round(dry_days_norm, 4),
        "rain_trigger": round(rain_trigger_value, 4),
        "impervious_norm": round(impervious_norm, 4),
        "load_index": round(load_index, 4),
        "runoff_index": round(runoff_index, 4),
        "risk_score": risk_score,
    }


if __name__ == "__main__":
    # 문서 예시로 간단히 자체 검증: CSV의 테헤란로(AADT=40890)를 표본(27041~57125) 안에서 계산
    print("--- 비가 안 올 때 (위험도는 0에 가까워야 함) ---")
    print(calculate_full_risk(
        aadt=40890, aadt_sample_min=27041, aadt_sample_max=57125,
        antecedent_dry_days=5, is_raining=False,
        impervious_ratio_pct=57.72,
    ))

    print("--- 비가 와서 첫씻김 기준(8h 내 3mm) 충족했을 때 ---")
    print(calculate_full_risk(
        aadt=40890, aadt_sample_min=27041, aadt_sample_max=57125,
        antecedent_dry_days=5, is_raining=True,
        cumulative_mm_since_rain_start=4.0, hours_since_rain_start=2.0,
        impervious_ratio_pct=57.72,
    ))
