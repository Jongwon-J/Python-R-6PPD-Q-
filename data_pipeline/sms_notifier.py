"""
sms_notifier.py - Solapi 기반 SMS 발송 (담당 공무원 대상 내부 알림)

역할:
    대국민 긴급재난문자(CBS)가 아니라, 하천 관리를 담당하는 공무원 개인에게 등급 변화를
    즉시 알려주는 내부 알림입니다. 소방청 등이 운영하는 국가재난안전통신망과는 무관하고,
    국내 상용 SMS API(Solapi)로 담당자 휴대폰에 바로 보내는 방식이라 별도 인허가가 필요
    없습니다 — 사내(부서 내) 당직 알림, PagerDuty 알림 같은 것과 같은 성격입니다.

    (Twilio 체험 계정은 한국(+82) 번호를 SMS/전화 어느 방식으로도 인증할 수 없어 국내
    발송이 원천적으로 막혀 있었습니다 — Twilio 자체의 체험 계정 정책 제약. Solapi는
    국내 서비스라 이 제약이 없고, 개인(비사업자) 가입도 지원하며 가입 시 무료 포인트가
    지급됩니다.)

Solapi 설정 (사업자등록 불필요):
    1) solapi.com 가입 (개인 회원가입 가능, 가입 시 무료 포인트 지급)
    2) console.solapi.com > 발신번호 관리 에서 본인 휴대폰 번호를 발신번호로 등록
       (본인인증만으로 가능 — 국내 통신 관련 법상 모든 SMS 발신번호는 사전 등록이
        필수이며, Twilio의 '체험 계정 제약'과는 다른, 국내 서비스라면 어디든 적용되는
        절차입니다. 이걸 먼저 안 해두면 발송 시 오류가 납니다.)
    3) console.solapi.com > API Key 관리 에서 API Key / API Secret 발급
    4) .env에 SOLAPI_API_KEY / SOLAPI_API_SECRET / SOLAPI_FROM_NUMBER / SOLAPI_TO_NUMBER
       4개 추가 (FROM/TO 모두 010XXXXXXXX 형식, 하이픈 없이 숫자만)

실행 (단독 테스트):
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
    """
    SMS 발송. Solapi 환경변수가 없거나 발송이 실패해도 예외를 상위로 던지지 않고 False만
    반환합니다 — SMS 하나 실패했다고 전체 파이프라인(위험도 계산, 문서 생성)이 멈추면 안 되기
    때문입니다.
    """
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
