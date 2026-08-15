"""공통 설정: 환경변수 로드 + LLM 팩토리.

환경변수(.env):
- GEMINI_API_KEY : Gemini(AI Studio) 키. ChatGoogleGenerativeAI 가 자동으로 읽는다.
- GEMINI_MODEL   : 사용할 모델명 (기본 gemini-3.1-flash-lite, 무료 티어).
- GEMINI_RPM     : 분당 요청 상한 (기본 12). 무료 티어 한도가 15 라 여유를 둔다.
                   유료 전환 시 크게 올려도 된다.

주의: 여기서 쓰는 GEMINI_API_KEY(=Gemini)와
google_clients.py 의 OAuth(credentials.json/token.json, Sheets·Gmail)는 서로 다른 인증이다.
"""
import os

from dotenv import load_dotenv
from langchain_core.rate_limiters import InMemoryRateLimiter
from langchain_google_genai import ChatGoogleGenerativeAI

from agents.usage import USAGE

load_dotenv()

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
GEMINI_RPM = float(os.getenv("GEMINI_RPM", "12"))


def get_llm(temperature: float = 0.3) -> ChatGoogleGenerativeAI:
    """에이전트들이 공유하는 LLM 인스턴스를 만든다.

    rate_limiter 로 분당 요청을 미리 눌러 429 자체가 잘 안 나게 하고,
    USAGE 콜백으로 모든 호출의 토큰 사용량을 누적한다.
    """
    if not os.getenv("GEMINI_API_KEY"):
        raise RuntimeError("GEMINI_API_KEY 가 설정되지 않았습니다 (.env 를 확인하세요).")
    limiter = InMemoryRateLimiter(
        requests_per_second=GEMINI_RPM / 60.0,
        check_every_n_seconds=0.1,
        max_bucket_size=max(1, int(GEMINI_RPM / 4)),   # 짧은 버스트 허용
    )
    return ChatGoogleGenerativeAI(model=GEMINI_MODEL, temperature=temperature,
                                  rate_limiter=limiter, callbacks=[USAGE])
