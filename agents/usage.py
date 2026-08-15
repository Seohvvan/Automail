"""LLM 토큰 사용량 집계 + 쿼터 초과(429) 재시도.

두 가지를 제공한다.

1) UsageTracker — 콜백 핸들러라 호출부를 고치지 않아도 모든 LLM 호출의
   usage_metadata(입력/출력 토큰)를 누적한다. get_llm() 에서 모델에 붙인다.
   실행 전후로 snapshot()/delta() 를 찍으면 그 구간의 실사용량이 나온다.

2) call_llm — 429 를 두 종류로 구분해 다르게 처리한다.
   - 분당 한도(PerMinute) 초과: 잠시 쉬었다 재시도하면 풀린다.
   - 일일 한도(PerDay) 소진: 자정(태평양시)까지 안 풀리므로 즉시 포기한다.
   에러 본문의 retryDelay 를 우선 따르고, 없으면 지수 백오프한다.
"""
import os
import re
import threading
import time

from langchain_core.callbacks import BaseCallbackHandler

# gemini-3.1-flash-lite 기준 100만 토큰당 단가(USD). 모델을 바꾸면 함께 조정한다.
PRICE_IN = float(os.getenv("GEMINI_PRICE_IN", "0.25"))
PRICE_OUT = float(os.getenv("GEMINI_PRICE_OUT", "1.50"))


class UsageTracker(BaseCallbackHandler):
    """모든 LLM 응답의 토큰 사용량을 누적한다 (스레드 세이프).

    백그라운드 워커 스레드에서 호출되므로 락으로 보호한다.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self.input_tokens = 0
        self.output_tokens = 0
        self.calls = 0

    def on_llm_end(self, response, **kwargs):  # noqa: ANN001 - LangChain 콜백 시그니처
        usage = self._extract(response)
        if not usage:
            return
        inp, out = usage
        with self._lock:
            self.input_tokens += inp
            self.output_tokens += out
            self.calls += 1

    @staticmethod
    def _extract(response):
        """LLMResult 에서 (입력, 출력) 토큰을 꺼낸다. 없으면 None."""
        for gens in getattr(response, "generations", []) or []:
            for gen in gens or []:
                msg = getattr(gen, "message", None)
                meta = getattr(msg, "usage_metadata", None)
                if meta:
                    return (meta.get("input_tokens", 0) or 0,
                            meta.get("output_tokens", 0) or 0)
        out = getattr(response, "llm_output", None) or {}
        tu = out.get("token_usage") or out.get("usage_metadata") or {}
        if tu:
            return (tu.get("prompt_tokens") or tu.get("input_tokens") or 0,
                    tu.get("completion_tokens") or tu.get("output_tokens") or 0)
        return None

    def snapshot(self):
        with self._lock:
            return (self.input_tokens, self.output_tokens, self.calls)

    def delta(self, snap):
        """snapshot() 이후 늘어난 사용량 dict."""
        i0, o0, c0 = snap
        i1, o1, c1 = self.snapshot()
        inp, out, calls = i1 - i0, o1 - o0, c1 - c0
        return {"input_tokens": inp, "output_tokens": out, "calls": calls,
                "usd": inp / 1e6 * PRICE_IN + out / 1e6 * PRICE_OUT}


USAGE = UsageTracker()   # 프로세스 전역 (LLM 인스턴스가 캐시되어 공유되므로)


def format_usage(d, companies=0, fx=1450):
    """진행 로그에 찍을 한 줄 요약."""
    msg = (f"입력 {d['input_tokens']:,} · 출력 {d['output_tokens']:,} 토큰 "
           f"({d['calls']:,}회 호출) → 약 ${d['usd']:.3f} ({d['usd'] * fx:,.0f}원)")
    if companies > 0:
        per = d["usd"] / companies
        msg += (f" | 업체당 ${per:.4f} ({per * fx:,.0f}원)"
                f" · 470곳 환산 ${per * 470:.2f} ({per * 470 * fx:,.0f}원)")
    return msg


# ---------- 429 재시도 ----------

_RETRY_DELAY_RE = re.compile(r"retryDelay['\"]?\s*:\s*['\"]?(\d+(?:\.\d+)?)s")
MAX_ATTEMPTS = int(os.getenv("GEMINI_RETRY_ATTEMPTS", "4"))
MAX_WAIT = float(os.getenv("GEMINI_RETRY_MAX_WAIT", "70"))


def _quota_kind(msg):
    """429 에러 문자열에서 쿼터 종류를 판별. 'day' | 'minute' | None(429 아님)."""
    if "429" not in msg and "RESOURCE_EXHAUSTED" not in msg:
        return None
    low = msg.lower()
    if "perday" in low or "per_day" in low or "requests per day" in low:
        return "day"
    return "minute"      # 분당/기타 일시적 한도로 간주


def call_llm(runnable, payload, on_event=None):
    """LLM 호출 + 429 재시도. 일일 쿼터 소진이면 재시도 없이 예외를 올린다."""
    last = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return runnable.invoke(payload)
        except Exception as e:  # noqa: BLE001 - 종류를 보고 재시도 여부를 정한다
            last = e
            kind = _quota_kind(str(e))
            if kind is None or kind == "day" or attempt == MAX_ATTEMPTS:
                raise
            m = _RETRY_DELAY_RE.search(str(e))
            wait = min(float(m.group(1)) + 1 if m else 2 ** attempt, MAX_WAIT)
            if on_event:
                on_event(f"[대기] 분당 요청 한도 초과 — {wait:.0f}초 후 재시도 "
                         f"({attempt}/{MAX_ATTEMPTS - 1})")
            time.sleep(wait)
    raise last
