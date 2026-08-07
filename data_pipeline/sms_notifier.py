"""
sms_notifier.py - Solapi 기반 SMS 발송 (담당 공무원 대상 내부 알림)

대국민 긴급재난문자가 아니라 담당 공무원 개인에게 보내는 내부 알림이라 별도 인허가가 필요 없다.
설정: solapi.com 가입 → 발신번호 등록 → API Key 발급 → .env에 SOLAPI_API_KEY/API_SECRET/
FROM_NUMBER/TO_NUMBER 등록.

    python sms_notifier.py "테스트 메시지"
"""

import os
import sys
import logging

from dotenv import load_dotenv
from solapi import SolapiMessageService
from solapi.model import RequestMessage

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("sms_notifier")

SOLAPI_API_KEY = os.environ.get("SOLAPI_API_KEY")
SOLAPI_API_SECRET = os.environ.get("SOLAPI_API_SECRET")
SOLAPI_FROM_NUMBER = os.environ.get("SOLAPI_FROM_NUMBER")
SOLAPI_TO_NUMBER = os.environ.get("SOLAPI_TO_NUMBER")


def is_configured() -> bool:
    return all([SOLAPI_API_KEY, SOLAPI_API_SECRET, SOLAPI_FROM_NUMBER, SOLAPI_TO_NUMBER])


def send_sms(message: str) -> bool:
    """SMS 발송. 실패해도 예외를 던지지 않고 False만 반환 — SMS 하나 실패했다고
    전체 파이프라인(위험도 계산, 문서 생성)이 멈추면 안 되기 때문."""
    if not is_configured():
        logger.warning(
            "Solapi 환경변수 미설정 — SMS 발송 건너뜀 "
            "(.env에 SOLAPI_API_KEY/API_SECRET/FROM_NUMBER/TO_NUMBER 필요)"
        )
        return False
    try:
        service = SolapiMessageService(api_key=SOLAPI_API_KEY, api_secret=SOLAPI_API_SECRET)
        msg = RequestMessage(from_=SOLAPI_FROM_NUMBER, to=SOLAPI_TO_NUMBER, text=message)
        response = service.send(msg)
        logger.info(f"SMS 발송 완료 ({response})")
        return True
    except Exception as e:
        logger.error(f"SMS 발송 실패: {e}")
        return False


if __name__ == "__main__":
    text = sys.argv[1] if len(sys.argv) > 1 else "[6PPD-Q 테스트] sms_notifier.py 단독 실행 테스트 메시지입니다."
    ok = send_sms(text)
    sys.exit(0 if ok else 1)
