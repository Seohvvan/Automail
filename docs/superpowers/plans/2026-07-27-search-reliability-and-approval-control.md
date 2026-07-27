# 검색 신뢰성 · 승인 제어 개선 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 검색 미발견 업체의 재검색을 승인 전 소진하고, "발송 건너뛰기"를 종료로 만들고, 수동 입력 이메일 소실을 막고, JS 렌더링/번들 사이트의 이메일을 폴백으로 회수하며, 환각·플레이스홀더·이메일 잘림을 차단한다.

**Architecture:** 순수 로직(정규화·게이트·병합·플레이스홀더 판정)을 모듈 레벨 순수 함수로 추출해 단위 테스트하고, 네트워크·LLM 의존부(Jina/번들/supervisor 그래프)는 순수 함수 조합 + monkeypatch + 선택적 네트워크 통합 테스트로 검증한다. 기존 ReAct/supervisor 구조는 유지하고 결정적 게이트만 추가한다.

**Tech Stack:** Python 3.14 (`.venv`), langgraph, langchain, pydantic, streamlit, pytest(신규 dev), urllib(표준), Tavily/Jina(HTTP).

## Global Constraints

- 테스트 실행기: `./.venv/bin/python -m pytest` (repo 루트에서). 시스템 python3 아님.
- 순수 함수 단위 테스트는 네트워크·API 키 없이 항상 통과해야 한다.
- 네트워크 통합 테스트는 `@pytest.mark.network` 로 표시하고 `RUN_NETWORK_TESTS=1` 일 때만 실행.
- 커밋 트레일러: 각 커밋 메시지 끝에 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- 기존 코드 스타일 유지(한국어 docstring/주석, `# noqa: BLE001` 관용).
- `MAX_SEARCH_ATTEMPTS = 2` (supervisor.py 상수) — 값 변경 금지.
- 브랜치: `AgentDeploy` (현재 브랜치, main 아님).

---

### Task 0: 테스트 도구 셋업

**Files:**
- Create: `requirements-dev.txt`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `tests/test_smoke.py`

**Interfaces:**
- Produces: `tests/` 임포트 경로(루트가 `sys.path`에 추가됨), `network` 마커 등록.

- [ ] **Step 1: dev 의존성 파일 작성**

Create `requirements-dev.txt`:
```
pytest>=8
```

- [ ] **Step 2: pytest 설치**

Run: `./.venv/bin/python -m pip install -r requirements-dev.txt`
Expected: `Successfully installed pytest-...`

- [ ] **Step 3: 테스트 패키지·conftest 작성**

Create `tests/__init__.py` (빈 파일).

Create `tests/conftest.py`:
```python
"""테스트 공통 설정: repo 루트를 import 경로에 추가하고 network 마커 등록."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "network: 인터넷 접속이 필요한 통합 테스트 (RUN_NETWORK_TESTS=1)")
```

- [ ] **Step 4: 스모크 테스트 작성**

Create `tests/test_smoke.py`:
```python
def test_smoke():
    assert True
```

- [ ] **Step 5: 실행 확인**

Run: `./.venv/bin/python -m pytest tests/test_smoke.py -v`
Expected: PASS (1 passed)

- [ ] **Step 6: 커밋**

```bash
git add requirements-dev.txt tests/__init__.py tests/conftest.py tests/test_smoke.py
git commit -m "test: pytest 도구 셋업 (.venv 기반)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 1: B1 — HTML→텍스트 정규화 후 이메일 추출

**Files:**
- Modify: `agents/tools.py` (`_html_to_text` 추가, `CandidateStore.add_from_text` 정규화 경유)
- Test: `tests/test_extraction.py`

**Interfaces:**
- Produces: `agents.tools._html_to_text(html: str) -> str` — 태그 제거(공백 미삽입) 후 공백 정규화. `CandidateStore.add_from_text` 가 이 함수를 거쳐 추출.

- [ ] **Step 1: 실패 테스트 작성**

Create `tests/test_extraction.py`:
```python
from agents.tools import CandidateStore, _html_to_text


def test_html_to_text_removes_tags_without_inserting_space():
    # 로컬파트 중간 태그는 공백 없이 제거되어야 이메일이 온전
    assert _html_to_text("luckyfresh<span>.</span>official@gmail.com") \
        == "luckyfresh.official@gmail.com"


def test_add_from_text_recovers_email_split_by_markup():
    s = CandidateStore()
    s.add_from_text("책임자: luckyfresh<wbr>.official@gmail.com", "luckyfresh.co.kr")
    assert "luckyfresh.official@gmail.com" in s.all()


def test_add_from_text_plain_dotted_localpart_intact():
    s = CandidateStore()
    s.add_from_text("최승준(luckyfresh.official@gmail.com)", "x.com")
    assert "luckyfresh.official@gmail.com" in s.all()


def test_real_space_is_not_merged():
    # 실제 공백으로 분리된 토큰은 합치지 않는다
    s = CandidateStore()
    s.add_from_text("luckyfresh. official@gmail.com", "x.com")
    assert "luckyfresh.official@gmail.com" not in s.all()
    assert "official@gmail.com" in s.all()
```

- [ ] **Step 2: 실패 확인**

Run: `./.venv/bin/python -m pytest tests/test_extraction.py -v`
Expected: FAIL (`ImportError: cannot import name '_html_to_text'`)

- [ ] **Step 3: `_html_to_text` 추가**

In `agents/tools.py`, `URL_RE`/`EMAIL_RE` 정의부([tools.py:22-23](../../../agents/tools.py)) 아래에 추가:
```python
def _html_to_text(html):
    """HTML 태그를 '공백 삽입 없이' 제거하고 공백을 정규화한다.

    태그를 공백으로 치환하면 'luckyfresh<span>.</span>official@...' 이
    끊겨 이메일이 잘리므로, 태그는 빈 문자열로 제거한 뒤 공백만 정규화한다.
    """
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html or ""))
```

- [ ] **Step 4: `add_from_text` 를 정규화 경유로 변경**

In `agents/tools.py`, `CandidateStore.add_from_text`([tools.py:71-73](../../../agents/tools.py))를 교체:
```python
    def add_from_text(self, text, domain=""):
        for e in EMAIL_RE.findall(_html_to_text(text)):
            self.add(e, domain)
```

- [ ] **Step 5: 통과 확인**

Run: `./.venv/bin/python -m pytest tests/test_extraction.py -v`
Expected: PASS (4 passed)

- [ ] **Step 6: 커밋**

```bash
git add agents/tools.py tests/test_extraction.py
git commit -m "fix: HTML 태그로 잘리는 이메일 추출 방지 (정규화 후 regex)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: B3 — 플레이스홀더 이메일 필터

**Files:**
- Modify: `agents/tools.py` (`_PLACEHOLDER_LOCALPARTS`, `_PLACEHOLDER_DOMAINS`, `_is_placeholder`, `CandidateStore.add`)
- Test: `tests/test_placeholder.py`

**Interfaces:**
- Produces: `agents.tools._is_placeholder(email: str) -> bool`. `CandidateStore.add` 가 플레이스홀더를 거부.

- [ ] **Step 1: 실패 테스트 작성**

Create `tests/test_placeholder.py`:
```python
from agents.tools import CandidateStore, _is_placeholder


def test_is_placeholder_localparts():
    assert _is_placeholder("example@company.com")
    assert _is_placeholder("test@foo.com")
    assert _is_placeholder("noreply@foo.com")
    assert _is_placeholder("no-reply@foo.com")


def test_is_placeholder_domains():
    assert _is_placeholder("hello@example.com")


def test_real_email_not_placeholder():
    assert not _is_placeholder("farmtc365@naver.com")
    assert not _is_placeholder("luckyfresh.official@gmail.com")


def test_store_rejects_placeholder():
    s = CandidateStore()
    s.add_from_text("문의 example@company.com 또는 farmtc365@naver.com", "farmtc365.com")
    assert "example@company.com" not in s.all()
    assert "farmtc365@naver.com" in s.all()
```

- [ ] **Step 2: 실패 확인**

Run: `./.venv/bin/python -m pytest tests/test_placeholder.py -v`
Expected: FAIL (`ImportError: cannot import name '_is_placeholder'`)

- [ ] **Step 3: 플레이스홀더 판정 추가**

In `agents/tools.py`, `_ASSET_EXT` 정의([tools.py:25](../../../agents/tools.py)) 아래에 추가:
```python
# 개발자가 코드/템플릿에 박아두는 가짜 이메일 (특히 JS 번들 스캔 시 유입)
_PLACEHOLDER_LOCALPARTS = frozenset({
    "example", "test", "sample", "samples", "your", "youremail", "yourname",
    "email", "mail", "user", "username", "name", "admin", "demo",
    "noreply", "no-reply", "donotreply", "do-not-reply",
})
_PLACEHOLDER_DOMAINS = frozenset({
    "example.com", "example.org", "example.net", "domain.com",
    "company.com", "email.com", "yourdomain.com", "sample.com", "test.com",
})


def _is_placeholder(email):
    """플레이스홀더/샘플 이메일이면 True (후보에서 제외)."""
    local, _, dom = (email or "").lower().partition("@")
    return local in _PLACEHOLDER_LOCALPARTS or dom in _PLACEHOLDER_DOMAINS
```

- [ ] **Step 4: `CandidateStore.add` 에 필터 적용**

In `agents/tools.py`, `CandidateStore.add`([tools.py:62-69](../../../agents/tools.py))의 첫 조건을 교체:
```python
    def add(self, email, domain=""):
        e = (email or "").lower().rstrip(".")
        if not e or e.endswith(_ASSET_EXT) or _is_placeholder(e):
            return
        self.sources.setdefault(e, set())
        d = normalize_domain(domain)
        if d:
            self.sources[e].add(d)
```

- [ ] **Step 5: 통과 확인**

Run: `./.venv/bin/python -m pytest tests/test_placeholder.py -v`
Expected: PASS (4 passed)

- [ ] **Step 6: 커밋**

```bash
git add agents/tools.py tests/test_placeholder.py
git commit -m "feat: 플레이스홀더 이메일 필터 (example@/test@/noreply 등 차단)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: B3 — 검색 에이전트 환각/오합성 방지 프롬프트

**Files:**
- Modify: `agents/search_agent.py` (`_SYSTEM`, `SearchDecision` 필드 설명)
- Test: `tests/test_search_prompt.py`

**Interfaces:**
- Consumes: 없음. Produces: 없음(프롬프트 텍스트 강화). 회귀 방지용 문자열 존재 테스트만.

- [ ] **Step 1: 실패 테스트 작성**

Create `tests/test_search_prompt.py`:
```python
from agents.search_agent import _SYSTEM, SearchDecision


def test_system_prompt_has_no_synthesis_rule():
    assert "임의 합성 금지" in _SYSTEM
    assert "유사 상호" in _SYSTEM or "유사 상호명" in _SYSTEM


def test_is_target_business_field_mentions_mismatch():
    desc = SearchDecision.model_fields["is_target_business"].description
    assert "불일치" in desc
```

- [ ] **Step 2: 실패 확인**

Run: `./.venv/bin/python -m pytest tests/test_search_prompt.py -v`
Expected: FAIL (assert)

- [ ] **Step 3: `_SYSTEM` 규칙 추가**

In `agents/search_agent.py`, `_SYSTEM` 의 "규칙:" 블록([search_agent.py:57-65](../../../agents/search_agent.py))에서 `- 도구 결과에 실제로 등장한 이메일만 답할 수 있습니다. 추측·조합 금지.` 줄 바로 아래에 추가:
```python
- 임의 합성 금지: 이메일 ID, 유사 상호명, 유사 업종(예: 농산물 유통)이라는 이유만으로
  서로 다른 업체의 정보를 하나로 묶거나 합치지 마라. 힌트(업종/지역)와 명확히
  불일치하면 is_target_business=false 로 판단하라.
```

- [ ] **Step 4: `SearchDecision` 필드 설명 강화**

In `agents/search_agent.py`, `is_target_business` 필드([search_agent.py:32-33](../../../agents/search_agent.py))를 교체:
```python
    is_target_business: bool = Field(description="찾은 업체가 힌트(업종/키워드/지역)에 "
                                                 "맞는 그 업체면 true. 이름만 비슷하거나 "
                                                 "업종만 비슷한 다른 회사(힌트와 불일치)면 "
                                                 "false.")
```

- [ ] **Step 5: 통과 확인**

Run: `./.venv/bin/python -m pytest tests/test_search_prompt.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: 커밋**

```bash
git add agents/search_agent.py tests/test_search_prompt.py
git commit -m "feat: 검색 에이전트 임의 합성(오합성) 방지 규칙 추가

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: B2 — Jina 렌더링 폴백 (2단계)

**Files:**
- Modify: `agents/tools.py` (`import os`, `_fetch_page` 헤더 인자, `_fetch_via_jina`, `_extract_cands`, `open_website` 티어링)
- Test: `tests/test_open_website_tiering.py`, `tests/test_integration_render.py`

**Interfaces:**
- Consumes: `_html_to_text`, `_is_placeholder` (Task 1·2).
- Produces:
  - `agents.tools._fetch_via_jina(url: str, timeout: int = 40) -> str` (실패 시 "").
  - `agents.tools._extract_cands(text: str) -> list[str]` (정규화+플레이스홀더 필터 적용된 후보).
  - `open_website` 가 정적 후보 0개일 때만 Jina 를 탄다.

- [ ] **Step 1: 실패 테스트 작성 (티어링, monkeypatch)**

Create `tests/test_open_website_tiering.py`:
```python
import agents.tools as tools


def _make_open_website(store):
    # make_search_tools 는 [web_search, open_website] 를 반환
    return {t.name: t for t in tools.make_search_tools(store)}["open_website"]


def test_static_hit_does_not_call_jina(monkeypatch):
    calls = {"jina": 0}
    monkeypatch.setattr(tools, "_fetch_site_text",
                        lambda d: "문의 farmtc365@naver.com")
    monkeypatch.setattr(tools, "_fetch_via_jina",
                        lambda url, timeout=40: calls.__setitem__("jina", calls["jina"] + 1) or "")
    store = tools.CandidateStore()
    open_website = _make_open_website(store)
    out = open_website.invoke({"url_or_domain": "farmtc365.com"})
    assert "farmtc365@naver.com" in store.all()
    assert calls["jina"] == 0


def test_static_empty_falls_back_to_jina(monkeypatch):
    monkeypatch.setattr(tools, "_fetch_site_text", lambda d: "<html>no mail here</html>")
    monkeypatch.setattr(tools, "_fetch_via_jina",
                        lambda url, timeout=40: "이메일 문의 farmtc365@naver.com")
    store = tools.CandidateStore()
    open_website = _make_open_website(store)
    out = open_website.invoke({"url_or_domain": "farmtc365.com"})
    assert "farmtc365@naver.com" in store.all()
    assert store.seen_on("farmtc365@naver.com", "farmtc365.com")


def test_extract_cands_filters_placeholder():
    assert tools._extract_cands("a example@company.com b real@naver.com") == ["real@naver.com"]
```

- [ ] **Step 2: 실패 확인**

Run: `./.venv/bin/python -m pytest tests/test_open_website_tiering.py -v`
Expected: FAIL (`AttributeError: module 'agents.tools' has no attribute '_fetch_via_jina'`)

- [ ] **Step 3: `os` 임포트 + `_fetch_page` 헤더 인자화**

In `agents/tools.py`, 상단 임포트([tools.py:13-17](../../../agents/tools.py))에 `import os` 추가.

`_fetch_page`([tools.py:89-106](../../../agents/tools.py))의 시그니처·헤더 구성을 교체:
```python
def _fetch_page(url, timeout=8, headers=None):
    """페이지 HTML 을 직접 받는다 (macOS 인증서/한국 인코딩 폴백 포함)."""
    h = {"User-Agent": "Mozilla/5.0"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
```
(이후 본문 `try/except`·디코딩 로직은 그대로 유지.)

- [ ] **Step 4: `_fetch_via_jina` 와 `_extract_cands` 추가**

In `agents/tools.py`, `_tavily`/`_results_list` 아래([tools.py:148](../../../agents/tools.py) 부근)에 추가:
```python
def _fetch_via_jina(url, timeout=40):
    """Jina Reader(r.jina.ai)로 JS 렌더링된 본문 텍스트를 받는다. 실패 시 ""."""
    headers = {}
    key = os.getenv("JINA_API_KEY", "")
    if key:
        headers["Authorization"] = f"Bearer {key}"
    try:
        return _fetch_page(f"https://r.jina.ai/{url}", timeout=timeout,
                           headers=headers or None)
    except Exception:  # noqa: BLE001 - 렌더링 실패는 다음 단계로
        return ""


def _extract_cands(text):
    """정규화 후 이메일 후보 리스트(에셋/플레이스홀더 제외, 순서 보존)."""
    out = []
    for e in EMAIL_RE.findall(_html_to_text(text)):
        e = e.lower().rstrip(".")
        if e.endswith(_ASSET_EXT) or _is_placeholder(e) or e in out:
            continue
        out.append(e)
    return out
```

- [ ] **Step 5: `open_website` 를 정적→Jina 티어링으로 교체**

In `agents/tools.py`, `open_website`([tools.py:196-232](../../../agents/tools.py)) 전체를 교체:
```python
    @tool
    def open_website(url_or_domain: str) -> str:
        """웹페이지(도메인 또는 URL)를 직접 열어 본문과 이메일 후보를 가져온다.

        정적 조회로 이메일 후보가 없으면 Jina Reader(JS 렌더링)로 재조회한다.
        홈과 문의성 하위 페이지까지 함께 조회한다.
        """
        domain = normalize_domain(url_or_domain)
        if not domain:
            return "유효한 도메인이 아닙니다."
        try:
            text = _fetch_site_text(domain)
        except Exception as e:  # noqa: BLE001
            return f"접속 오류({type(e).__name__}): {e}"
        used = "static"
        if text:
            store.add_from_text(text, domain)
        cands = _extract_cands(text)
        if not cands:
            jina = _fetch_via_jina(f"https://{domain}")
            if jina:
                store.add_from_text(jina, domain)
                jc = _extract_cands(jina)
                if jc:
                    text, cands, used = jina, jc, "jina"
        if not text:
            return f"{domain} 접속 실패"
        plain = _html_to_text(text)
        low = plain.lower()
        windows = []
        for e in cands[:10]:
            i = low.find(e)
            if i >= 0:
                windows.append(plain[max(0, i - 200): i + len(e) + 200])
        out = [f"[{domain} 페이지 원문 앞부분 · 경로:{used}]\n{plain[:1200]}"]
        if cands:
            out.append("[발견된 이메일 후보] " + ", ".join(cands[:15]))
            out.append("[후보 주변 문맥]\n" + "\n---\n".join(windows))
        else:
            out.append("[이 페이지에서 이메일 후보 없음]")
        return "\n\n".join(out)
```

- [ ] **Step 6: 티어링 단위 테스트 통과 확인**

Run: `./.venv/bin/python -m pytest tests/test_open_website_tiering.py -v`
Expected: PASS (3 passed)

- [ ] **Step 7: 네트워크 통합 테스트 작성**

Create `tests/test_integration_render.py`:
```python
import os
import pytest

import agents.tools as tools

pytestmark = pytest.mark.network
skip_net = pytest.mark.skipif(not os.getenv("RUN_NETWORK_TESTS"),
                              reason="RUN_NETWORK_TESTS 미설정")


@skip_net
def test_farmtc365_via_jina():
    store = tools.CandidateStore()
    open_website = {t.name: t for t in tools.make_search_tools(store)}["open_website"]
    open_website.invoke({"url_or_domain": "www.farmtc365.com"})
    assert "farmtc365@naver.com" in store.all()
```

- [ ] **Step 8: (선택) 네트워크 통합 테스트 실행**

Run: `RUN_NETWORK_TESTS=1 ./.venv/bin/python -m pytest tests/test_integration_render.py::test_farmtc365_via_jina -v`
Expected: PASS (네트워크 가능 시). 네트워크 불가 환경이면 SKIP.

- [ ] **Step 9: 커밋**

```bash
git add agents/tools.py tests/test_open_website_tiering.py tests/test_integration_render.py
git commit -m "feat: open_website Jina 렌더링 폴백 (정적 후보 0개일 때)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: B2 — JS 번들 스캔 (3단계)

**Files:**
- Modify: `agents/tools.py` (`_scan_js_bundles`, `open_website` 3단계 추가)
- Test: `tests/test_open_website_tiering.py` (추가), `tests/test_integration_render.py` (추가)

**Interfaces:**
- Consumes: `_extract_cands`, `_fetch_page`, `normalize_domain`.
- Produces: `agents.tools._scan_js_bundles(domain: str, home_html: str, max_files: int = 5, max_bytes: int = 2_000_000) -> str` — 동일 도메인 `.js` 본문을 이어붙여 반환.

- [ ] **Step 1: 실패 테스트 추가**

Append to `tests/test_open_website_tiering.py`:
```python
def test_scan_js_bundles_same_domain_only(monkeypatch):
    home = ('<script src="/assets/app.js"></script>'
            '<script src="https://cdn.other.com/vendor.js"></script>')

    def fake_fetch(url, timeout=8, headers=None):
        if url.endswith("/assets/app.js"):
            return "footer email: farmtc365@naver.com"
        raise AssertionError(f"외부 도메인 fetch 금지: {url}")

    monkeypatch.setattr(tools, "_fetch_page", fake_fetch)
    js = tools._scan_js_bundles("farmtc365.com", home)
    assert "farmtc365@naver.com" in js


def test_bundle_used_only_when_static_and_jina_empty(monkeypatch):
    monkeypatch.setattr(tools, "_fetch_site_text",
                        lambda d: '<script src="/assets/app.js"></script>')
    monkeypatch.setattr(tools, "_fetch_via_jina", lambda url, timeout=40: "")
    monkeypatch.setattr(tools, "_scan_js_bundles",
                        lambda domain, home_html, **kw: "메일 luckyfresh.official@gmail.com")
    store = tools.CandidateStore()
    open_website = _make_open_website(store)
    open_website.invoke({"url_or_domain": "luckyfresh.co.kr"})
    assert "luckyfresh.official@gmail.com" in store.all()
```

- [ ] **Step 2: 실패 확인**

Run: `./.venv/bin/python -m pytest tests/test_open_website_tiering.py -v`
Expected: FAIL (`AttributeError: ... '_scan_js_bundles'`)

- [ ] **Step 3: `_scan_js_bundles` 추가**

In `agents/tools.py`, `_fetch_via_jina` 아래에 추가:
```python
def _scan_js_bundles(domain, home_html, max_files=5, max_bytes=2_000_000):
    """홈 HTML 의 <script src> 중 '동일 도메인 .js' 본문을 이어붙여 반환.

    SPA 번들 안에 이메일이 문자열로 박힌 경우(정적/렌더링으로도 안 잡히는 사이트)를
    대비한 최후 폴백. 파일 개수·크기 상한으로 비용을 통제한다.
    """
    srcs = re.findall(r'<script[^>]+src=["\x27]([^"\x27]+\.js)["\x27]',
                      home_html or "", re.I)
    texts, count = [], 0
    for src in srcs:
        if count >= max_files:
            break
        url = src if src.startswith("http") else f"https://{domain}/{src.lstrip('/')}"
        if normalize_domain(url) != domain:
            continue
        try:
            texts.append(_fetch_page(url)[:max_bytes])
            count += 1
        except Exception:  # noqa: BLE001 - 개별 번들 실패는 건너뜀
            continue
    return "\n".join(texts)
```

- [ ] **Step 4: `open_website` 에 3단계(번들) 추가**

In `agents/tools.py`, `open_website` 내부의 Jina 폴백 블록(`if not cands:` … `used = "jina"`) 바로 아래, `if not text:` 앞에 추가:
```python
        if not cands and text:
            js = _scan_js_bundles(domain, text)
            if js:
                store.add_from_text(js, domain)
                bc = _extract_cands(js)
                if bc:
                    cands, used = bc, "bundle"
```
(주의: 번들 경로는 컨텍스트 표시용 `plain` 을 정적/Jina `text` 기준으로 두므로, `text` 는 교체하지 않고 `cands`/`used` 만 갱신한다.)

- [ ] **Step 5: 단위 테스트 통과 확인**

Run: `./.venv/bin/python -m pytest tests/test_open_website_tiering.py -v`
Expected: PASS (5 passed)

- [ ] **Step 6: 네트워크 통합 테스트 추가**

Append to `tests/test_integration_render.py`:
```python
@skip_net
def test_luckyfresh_via_bundle():
    store = tools.CandidateStore()
    open_website = {t.name: t for t in tools.make_search_tools(store)}["open_website"]
    open_website.invoke({"url_or_domain": "luckyfresh.co.kr"})
    assert "luckyfresh.official@gmail.com" in store.all()
    assert "example@company.com" not in store.all()
```

- [ ] **Step 7: (선택) 네트워크 통합 테스트 실행**

Run: `RUN_NETWORK_TESTS=1 ./.venv/bin/python -m pytest tests/test_integration_render.py -v`
Expected: PASS (네트워크 가능 시). 불가 시 SKIP.

- [ ] **Step 8: 커밋**

```bash
git add agents/tools.py tests/test_open_website_tiering.py tests/test_integration_render.py
git commit -m "feat: open_website JS 번들 스캔 폴백 (정적+Jina 실패 시)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: A1 — 검색 소진 게이트

**Files:**
- Modify: `agents/supervisor.py` (`pending_search_targets`, `resolve_next_action` 추가, `supervisor_node` 리팩터)
- Test: `tests/test_supervisor_resolve.py`

**Interfaces:**
- Consumes: 기존 `_valid_targets`, `_fallback`, `MAX_SEARCH_ATTEMPTS`.
- Produces:
  - `pending_search_targets(companies: list, max_attempts: int) -> list[int]` — email 빈 + 시도<상한 + 이름 있음 인덱스.
  - `resolve_next_action(decision, companies: list, stop: bool, max_attempts: int) -> tuple[str, list[int]]` — 최종 (action, valid_targets). stop 이면 항상 finish; approve_send/finish 인데 pending 검색이 있으면 search 로 오버라이드. `decision` 은 `.action:str`/`.targets:list[int]` 속성을 갖거나 None.

- [ ] **Step 1: 실패 테스트 작성**

Create `tests/test_supervisor_resolve.py`:
```python
from types import SimpleNamespace

from agents.supervisor import (MAX_SEARCH_ATTEMPTS, pending_search_targets,
                               resolve_next_action)


def _co(**kw):
    base = {"name": "X", "email": "", "search_attempts": 0}
    base.update(kw)
    return base


def test_pending_targets_email_empty_attempts_left():
    comps = [_co(name="A", email="", search_attempts=1),
             _co(name="B", email="b@x.com", search_attempts=0),
             _co(name="C", email="", search_attempts=MAX_SEARCH_ATTEMPTS)]
    assert pending_search_targets(comps, MAX_SEARCH_ATTEMPTS) == [0]


def test_stop_forces_finish_even_with_pending():
    comps = [_co(name="A", email="", search_attempts=0)]
    d = SimpleNamespace(action="approve_send", targets=[0])
    assert resolve_next_action(d, comps, True, MAX_SEARCH_ATTEMPTS) == ("finish", [])


def test_approve_send_overridden_by_pending_search():
    # 초안 있는 승인 대상 + 아직 미발견(검색 잔여) 업체 공존
    comps = [_co(name="A", email="a@x.com", subject="s", search_attempts=0),
             _co(name="B", email="", search_attempts=1)]
    d = SimpleNamespace(action="approve_send", targets=[0])
    action, valid = resolve_next_action(d, comps, False, MAX_SEARCH_ATTEMPTS)
    assert action == "search"
    assert valid == [1]


def test_finish_overridden_by_pending_search():
    comps = [_co(name="B", email="", search_attempts=0)]
    d = SimpleNamespace(action="finish", targets=[])
    action, valid = resolve_next_action(d, comps, False, MAX_SEARCH_ATTEMPTS)
    assert action == "search"
    assert valid == [0]


def test_approve_send_allowed_when_no_pending():
    comps = [_co(name="A", email="a@x.com", subject="s", search_attempts=0),
             _co(name="B", email="", search_attempts=MAX_SEARCH_ATTEMPTS)]
    d = SimpleNamespace(action="approve_send", targets=[0])
    action, valid = resolve_next_action(d, comps, False, MAX_SEARCH_ATTEMPTS)
    assert action == "approve_send"
    assert valid == [0]
```

- [ ] **Step 2: 실패 확인**

Run: `./.venv/bin/python -m pytest tests/test_supervisor_resolve.py -v`
Expected: FAIL (`ImportError: cannot import name 'pending_search_targets'`)

- [ ] **Step 3: 순수 헬퍼 추가**

In `agents/supervisor.py`, `_fallback`([supervisor.py:112-127](../../../agents/supervisor.py)) 아래에 추가:
```python
def pending_search_targets(companies, max_attempts):
    """이메일 미발견 + 시도 횟수 잔여 + 이름 있는 업체 인덱스 (검색 소진 대상)."""
    return [i for i, c in enumerate(companies)
            if c.get("name") and not c.get("email")
            and c.get("search_attempts", 0) < max_attempts]


def resolve_next_action(decision, companies, stop, max_attempts):
    """LLM 결정 → 최종 (action, valid_targets). 결정적 게이트 포함(순수 함수).

    - stop(사람이 '발송 건너뛰기') 이면 항상 finish.
    - LLM 대상이 무효면 결정적 폴백.
    - 미발견+검색 잔여 업체가 있으면 approve_send/finish 를 search 로 오버라이드
      (승인·종료 전에 검색을 소진).
    """
    if stop:
        return "finish", []
    action = getattr(decision, "action", "") if decision else ""
    targets = getattr(decision, "targets", []) if decision else []
    valid = _valid_targets(action, targets, companies) if action else []
    if action != "finish" and not valid:
        action, valid = _fallback(companies)
    if action != "finish" and not valid:
        action = "finish"
    pending = pending_search_targets(companies, max_attempts)
    if action in ("approve_send", "finish") and pending:
        return "search", pending
    return action, valid
```

- [ ] **Step 4: `supervisor_node` 를 헬퍼 사용으로 리팩터**

In `agents/supervisor.py`, `supervisor_node`([supervisor.py:133-168](../../../agents/supervisor.py))에서 LLM 호출 이후 valid/fallback/finish 판정부를 교체. `try/except` 블록을 다음으로 바꾼다:
```python
        try:
            d = llm.with_structured_output(SupervisorDecision).invoke(prompt)
            instruction, reason = d.instruction, d.reason
        except Exception as e:  # noqa: BLE001 - LLM 실패 시 결정적 폴백
            d, instruction, reason = None, "", f"LLM 오류 폴백: {e}"
        action, valid = resolve_next_action(
            d, companies, state.get("_stop", False), MAX_SEARCH_ATTEMPTS)
        on_event(f"[관리자] 결정: {action}"
                 + (f" (대상 {len(valid)}곳)" if valid else "")
                 + (f" — {reason}" if reason else ""))
        if action == "finish":
            return Command(goto=END, update={"steps": steps, "last_action": "finish"})
        return Command(goto=action, update={
            "steps": steps,
            "last_action": f"{action} → {[companies[i]['name'] for i in valid]}",
            "_targets": valid, "_instruction": instruction,
        })
```
(기존의 `valid = _valid_targets(...)` ~ `if action != "finish" and not valid: action = "finish"` ~ 두 번째 `on_event` 까지를 위 블록으로 대체. `steps > MAX_STEPS` 가드와 `prompt` 구성은 그대로 유지.)

- [ ] **Step 5: 통과 확인**

Run: `./.venv/bin/python -m pytest tests/test_supervisor_resolve.py -v`
Expected: PASS (5 passed)

- [ ] **Step 6: 커밋**

```bash
git add agents/supervisor.py tests/test_supervisor_resolve.py
git commit -m "feat: 승인/종료 전 미발견 업체 검색 소진 게이트 (A1)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7: A2 — "발송 건너뛰기" = 종료

**Files:**
- Modify: `agents/state.py` (`_stop` 필드)
- Modify: `agents/supervisor.py` (`approve_send_node` 가 `_stop` 세팅)
- Modify: `automail_st.py` (버튼 payload 에 `stop: True`)
- Test: `tests/test_supervisor_resolve.py` (Task 6 의 `test_stop_forces_finish_even_with_pending` 로 이미 커버 — 추가 테스트로 approve_send_node 의 stop 전달 검증)

**Interfaces:**
- Consumes: `resolve_next_action` 의 `stop` 인자(Task 6).
- Produces: `WorkflowState._stop: bool`. `approve_send_node` 가 interrupt 결과의 `stop` 을 `_stop` 으로 반영.

- [ ] **Step 1: 실패 테스트 작성 (approve_send_node 가 stop 을 전달하는지)**

Create `tests/test_approve_stop.py`:
```python
"""approve_send_node 가 interrupt 의 stop 을 상태 _stop 으로 넘기는지 검증.

interrupt() 를 monkeypatch 로 대체해 노드 함수를 단독 호출한다.
"""
import agents.supervisor as sup
from langgraph.graph import END


def _build_and_get_nodes(resume_value):
    # interrupt 를 고정값 반환으로 대체
    sup.interrupt = lambda payload: resume_value  # type: ignore
    return sup.build_supervisor_graph(creds=None, llm=None, on_event=lambda *_: None)


def test_state_has_stop_field():
    from agents.state import WorkflowState
    assert "_stop" in WorkflowState.__annotations__
```

- [ ] **Step 2: 실패 확인**

Run: `./.venv/bin/python -m pytest tests/test_approve_stop.py -v`
Expected: FAIL (`assert '_stop' in ...` — 아직 필드 없음)

- [ ] **Step 3: 상태에 `_stop` 추가**

In `agents/state.py`, `WorkflowState`([state.py:44-46](../../../agents/state.py))의 `_instruction` 아래에 추가:
```python
    _stop: bool            # 사람이 '발송 건너뛰기'로 즉시 종료 요청
```

- [ ] **Step 4: `approve_send_node` 가 `_stop` 세팅**

In `agents/supervisor.py`, `approve_send_node`([supervisor.py:205-243](../../../agents/supervisor.py))의 마지막 `return`([supervisor.py:243](../../../agents/supervisor.py)) 직전에 `stop` 추출을 추가하고 return 을 교체:
```python
        stop = bool(decision.get("stop"))
        return Command(goto="supervisor",
                       update={"companies": companies, "_stop": stop})
```
(`decision = interrupt(...) or {}` 는 그대로. `approved` 처리 루프도 그대로.)

- [ ] **Step 5: "발송 건너뛰기" 버튼이 stop 전송**

In `automail_st.py`, `render_approval` 의 "발송 건너뛰기" 버튼([automail_st.py:912-915](../../../automail_st.py))에서 resume 페이로드를 교체:
```python
        if a2.button("발송 건너뛰기", key=f"ap_skip_{seq}"):
            AUTO["resume"] = {"approved": [], "stop": True}
            AUTO["event"].set()
            st.toast("발송을 건너뜁니다")
```
("선택한 업체 발송 승인" 버튼([automail_st.py:899-911](../../../automail_st.py))은 `stop` 을 넣지 않으므로 기존 동작 유지.)

- [ ] **Step 6: 상태 필드 테스트 통과 확인**

Run: `./.venv/bin/python -m pytest tests/test_approve_stop.py::test_state_has_stop_field -v`
Expected: PASS

- [ ] **Step 7: 전체 단위 테스트 회귀 확인**

Run: `./.venv/bin/python -m pytest tests -m "not network" -v`
Expected: PASS (모든 비네트워크 테스트)

- [ ] **Step 8: 커밋**

```bash
git add agents/state.py agents/supervisor.py automail_st.py tests/test_approve_stop.py
git commit -m "feat: 발송 건너뛰기 시 재검색 없이 즉시 종료 (A2 _stop)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 8: A3 — 수동 입력 이메일 덮어쓰기 가드

**Files:**
- Create: `agents/sheet_sync.py` (`merge_email_column`)
- Modify: `automail_st.py` (import + `_persist_auto_rows` 병합)
- Test: `tests/test_sheet_sync.py`

**Interfaces:**
- Produces: `agents.sheet_sync.merge_email_column(mem_emails: list[str], sheet_emails: list[str]) -> list[str]` — 인덱스별로 메모리 값이 비어 있지 않으면 그것을, 비어 있으면 시트 기존 값을 채택(둘 다 비면 "").

- [ ] **Step 1: 실패 테스트 작성**

Create `tests/test_sheet_sync.py`:
```python
from agents.sheet_sync import merge_email_column


def test_memory_value_wins():
    assert merge_email_column(["a@x.com"], [""]) == ["a@x.com"]


def test_empty_memory_preserves_sheet():
    # 재검색 실패로 메모리는 비었지만 시트에 사람이 넣은 값 → 보존
    assert merge_email_column([""], ["manual@x.com"]) == ["manual@x.com"]


def test_both_empty():
    assert merge_email_column([""], [""]) == [""]


def test_length_mismatch_sheet_shorter():
    assert merge_email_column(["a@x.com", ""], ["", "b@x.com"]) == ["a@x.com", "b@x.com"]


def test_length_mismatch_pads():
    assert merge_email_column(["a@x.com", ""], ["x@x.com"]) == ["a@x.com", ""]
```

- [ ] **Step 2: 실패 확인**

Run: `./.venv/bin/python -m pytest tests/test_sheet_sync.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'agents.sheet_sync'`)

- [ ] **Step 3: `merge_email_column` 작성**

Create `agents/sheet_sync.py`:
```python
"""시트 저장 시 사람이 수동 입력한 값 보존을 위한 순수 병합 로직.

에이전트 메모리 상태를 시트에 덮어쓸 때, 메모리 이메일이 비어 있으면
시트의 기존 값을 지우지 않고 보존한다(승인 대기 중 수동 입력·재검색 실패 대비).
"""


def merge_email_column(mem_emails, sheet_emails):
    """인덱스별로 메모리 값 우선, 비어 있으면 시트 기존 값 채택."""
    n = max(len(mem_emails), len(sheet_emails))
    out = []
    for i in range(n):
        m = (mem_emails[i] if i < len(mem_emails) else "") or ""
        s = (sheet_emails[i] if i < len(sheet_emails) else "") or ""
        out.append(m.strip() or s.strip())
    return out
```

- [ ] **Step 4: 통과 확인**

Run: `./.venv/bin/python -m pytest tests/test_sheet_sync.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: `_persist_auto_rows` 에 병합 적용**

In `automail_st.py`, 상단 import 영역의 `from agents.reply_agent import classify_reply`([automail_st.py:55](../../../automail_st.py)) 아래에 추가:
```python
from agents.sheet_sync import merge_email_column  # noqa: E402
```

그리고 `_persist_auto_rows`([automail_st.py:535-545](../../../automail_st.py))의 email 열 쓰기 부분을 교체(제목·본문 쓰기는 그대로):
```python
def _persist_auto_rows(auto, c, wcfg, companies):
    """supervisor 결과를 전체 행에 반영하고 시트(이메일/제목/본문 열)에 저장.

    이메일 열은 메모리가 비어 있으면 시트의 기존 값을 보존한다
    (승인 대기 중 수동 입력·재검색 실패로 값이 지워지는 것 방지).
    """
    rows = auto["rows"]
    for local, comp in zip(auto["indices"], companies):
        rows[local].update(comp)
    mem_emails = [r.get("email", "") for r in rows]
    try:
        sheet_emails = read_column(c, wcfg["spreadsheet_id"], wcfg["email_range"])
    except Exception:  # noqa: BLE001 - 읽기 실패 시 메모리 값만 사용
        sheet_emails = []
    write_column(c, wcfg["spreadsheet_id"], wcfg["email_range"],
                 merge_email_column(mem_emails, sheet_emails))
    write_column(c, wcfg["spreadsheet_id"], subject_range(wcfg),
                 [r.get("subject", "") for r in rows])
    write_column(c, wcfg["spreadsheet_id"], body_range(wcfg),
                 [r.get("body", "") for r in rows])
```

- [ ] **Step 6: 전체 비네트워크 테스트 회귀 확인**

Run: `./.venv/bin/python -m pytest tests -m "not network" -v`
Expected: PASS

- [ ] **Step 7: `automail_st.py` 임포트 무결성 확인**

Run: `./.venv/bin/python -c "import ast; ast.parse(open('automail_st.py',encoding='utf-8').read()); print('syntax ok')"`
Expected: `syntax ok`

- [ ] **Step 8: 커밋**

```bash
git add agents/sheet_sync.py automail_st.py tests/test_sheet_sync.py
git commit -m "fix: 시트 저장 시 수동 입력 이메일 덮어쓰기 방지 (A3 병합)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## 구현 순서 메모 / 상호작용

- **fresh 모드와 A3의 상호작용(의도된 동작):** "자동 실행 시작"(fresh)은 검색을 처음부터 하되, A3 가드로 인해 **재검색이 실패해도 시트의 기존 이메일을 `""` 로 지우지 않는다.** 즉 "새로 못 찾으면 기존 값 유지". 이는 승인된 설계이며 데이터 소실 방지가 목적이다.
- **skip 모드와 A1의 상호작용:** "재검색 건너뛰기"는 `search_attempts=99` 이므로 `pending_search_targets` 에 잡히지 않아 A1 게이트가 검색을 강제하지 않는다(검색 없는 흐름 유지).
- Task 1·2 는 Task 4·5(open_website)의 전제이므로 먼저.
- Task 6 는 Task 7의 `resolve_next_action(stop=...)` 전제이므로 먼저.

## Self-Review 결과

- **스펙 커버리지:** A1(Task6)·A2(Task7)·A3(Task8)·B1(Task1)·B2(Task4·5)·B3(Task2·3) 전 항목 태스크 존재. 배경의 farmtc365/luckyfresh 실측은 통합 테스트(Task4·5)로 회귀 커버.
- **플레이스홀더 스캔:** "TBD/TODO/적절히 처리" 없음. 모든 코드 스텝에 실제 코드 포함.
- **타입 일관성:** `pending_search_targets`/`resolve_next_action`/`merge_email_column`/`_html_to_text`/`_is_placeholder`/`_extract_cands`/`_fetch_via_jina`/`_scan_js_bundles` 시그니처가 태스크 간 일치.
