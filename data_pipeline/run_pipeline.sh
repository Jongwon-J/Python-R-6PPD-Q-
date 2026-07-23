#!/bin/bash
# run_pipeline.sh - weather_collector -> etl_risk_pipeline -> crew_alert_agent를 순서대로 실행.
# cron은 로그인 셸이 아니라서 venv/환경변수를 못 읽는 경우가 많아, 이 스크립트 안에서
# cd + venv activate까지 전부 처리한 뒤 cron은 이 파일 하나만 호출하도록 구성했습니다.
#
# 등록 (crontab -e에 아래 한 줄 추가, 10분마다 실행):
#   */10 * * * * /Users/jeongjong-won/Desktop/Python-R-6PPD-Q-/data_pipeline/run_pipeline.sh >> /Users/jeongjong-won/Desktop/Python-R-6PPD-Q-/data_pipeline/pipeline.log 2>&1

set -e
cd "$(dirname "$0")"
source venv/bin/activate

echo "===== $(date '+%Y-%m-%d %H:%M:%S') 파이프라인 시작 ====="
python weather_collector.py
python etl_risk_pipeline.py
python crew_alert_agent.py
echo "===== $(date '+%Y-%m-%d %H:%M:%S') 파이프라인 종료 ====="
