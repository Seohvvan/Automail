"""멀티 에이전트 공용 도구 + grounding 후보 저장소.

에이전트(LLM)가 스스로 골라 호출하는 도구들을 정의한다.
- web_search   : Tavily 웹 검색 (도메인 한정 가능)
- open_website : 페이지 직접 조회 (검색 인덱스 미수록 대비)

grounding(환각 방지)은 도구 계층에서 결정적으로 보장한다:
모든 도구는 원문에서 정규식으로 이메일 후보를 추출해 CandidateStore 에
'어느 도메인에서 실제로 봤는지'와 함께 기록한다. 에이전트가 최종 답을 내면
코드는 (1) 후보 집합과 정확 일치하는지, (2) 공식 도메인에서 실제로 목격됐는지를
검사해 등급(HIGH/REVIEW/NONE)을 결정한다 — LLM 의 주장만으로 검증 O 를 주지 않는다.
"""
import os
import re
import ssl
import urllib.error
import urllib.request
from urllib.parse import urlparse

from langchain_core.tools import tool
from langchain_tavily import TavilySearch

URL_RE = re.compile(r"https?://\S+|www\.\S+")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def _html_to_text(html):
    """HTML 태그를 '공백 삽입 없이' 제거하고 공백을 정규화한다.

    태그를 공백으로 치환하면 'luckyfresh<span>.</span>official@...' 이
    끊겨 이메일이 잘리므로, 태그는 빈 문자열로 제거한 뒤 공백만 정규화한다.
    """
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html or ""))


# Cloudflare 이메일 난독화: 실제 주소가 data-cfemail(또는 email-protection#) 의
# 16진 문자열로 인코딩되고 JS(email-decode.min.js)로 복원된다. 정적/렌더링 텍스트엔
# '[email protected]' 만 남으므로, 여기서 직접 디코딩해 원래 주소를 회수한다.
_CFEMAIL_RE = re.compile(
    r'data-cfemail=["\x27]([0-9a-fA-F]{4,})["\x27]'
    r'|/cdn-cgi/l/email-protection#([0-9a-fA-F]{4,})')


def _decode_cfemail(hexstr):
    """Cloudflare data-cfemail 16진 문자열을 원래 이메일로 복원한다.

    첫 바이트가 XOR 키이고, 이후 각 바이트를 키와 XOR 하면 원래 문자가 된다.
    """
    try:
        key = int(hexstr[:2], 16)
        return "".join(chr(int(hexstr[i:i + 2], 16) ^ key)
                       for i in range(2, len(hexstr), 2))
    except (ValueError, IndexError):
        return ""


def _cf_emails(html):
    """HTML 에서 Cloudflare 로 가려진 이메일들을 복원해 리스트로 반환(중복 제거)."""
    out = []
    for m in _CFEMAIL_RE.finditer(html or ""):
        dec = _decode_cfemail(m.group(1) or m.group(2)).lower()
        if EMAIL_RE.fullmatch(dec) and dec not in out:
            out.append(dec)
    return out


def _emails_from_text(text):
    """HTML/텍스트에서 이메일 후보를 뽑는다.

    두 정규화를 함께 사용한다:
      - 태그 제거(공백 없이): 로컬파트 중간 태그로 잘린 이메일 복구
        (luckyfresh<span>.</span>official@... → luckyfresh.official@...)
      - 태그를 공백으로: 인접 태그 사이 서로 다른 이메일이 붙어 유실되는 것 방지
    그리고 '태그로 잘린 조각'만 제거한다: 조각은 공백 패스에만 있고(전체 이메일은
    태그제거 패스에서 복원됨) 태그제거 후보의 '.' 경계 접미사인 경우다. 평문에서
    우연히 접미사가 겹치는 '서로 다른 실제 이메일'(info@a.com vs kim.info@a.com)은
    양쪽 패스에 모두 나타나므로 지우지 않는다.
    """
    def extract(s):
        seen = []
        for e in EMAIL_RE.findall(s):
            e = e.lower().rstrip(".")
            if e and e not in seen:
                seen.append(e)
        return seen

    empty = extract(_html_to_text(text))
    spaced = extract(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")))
    empty_set = set(empty)
    out = []
    for e in empty + spaced:
        if e in out:
            continue
        if e not in empty_set and any(
                y != e and y.endswith(e) and y[:-len(e)].endswith(".")
                for y in empty):
            continue  # 공백 패스에만 있는 '.' 경계 접미사 = 태그로 잘린 조각
        out.append(e)
    # Cloudflare 로 가려진 이메일 복원(텍스트엔 '[email protected]' 만 남으므로 별도 처리)
    for e in _cf_emails(text):
        if e not in out:
            out.append(e)
    return out


# 이미지 파일명 등이 이메일 패턴에 오인 매칭되는 것 방지 (예: icon@2x.png)
_ASSET_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".css", ".js", ".ico")
# 개발자가 코드/템플릿에 박아두는 가짜 이메일 (특히 JS 번들 스캔 시 유입)
_PLACEHOLDER_LOCALPARTS = frozenset({
    "example", "test", "sample", "samples", "your", "youremail", "yourname",
    "username", "demo", "noreply", "no-reply", "donotreply", "do-not-reply",
})
_PLACEHOLDER_DOMAINS = frozenset({
    "example.com", "example.org", "example.net", "domain.com",
    "company.com", "email.com", "yourdomain.com", "sample.com", "test.com",
})


def _is_placeholder(email):
    """플레이스홀더/샘플 이메일이면 True (후보에서 제외)."""
    local, _, dom = (email or "").lower().partition("@")
    return local in _PLACEHOLDER_LOCALPARTS or dom in _PLACEHOLDER_DOMAINS


# 직접 조회 시 홈에서 추적할 문의성 하위 페이지 링크
_CONTACT_LINK_RE = re.compile(
    r"contact|about|company|support|guide|agreement|privacy|문의|회사|고객", re.I)


def normalize_domain(s):
    """'https://www.example.com/path' → 'example.com'."""
    s = (s or "").strip()
    if not s:
        return ""
    if "://" not in s:
        s = "https://" + s
    host = (urlparse(s).netloc or "").split("@")[-1].split(":")[0].lower()
    return host[4:] if host.startswith("www.") else host


def split_hint(hint):
    """힌트에서 URL 을 분리해 (업종 텍스트, 도메인) 반환. URL 이 없으면 도메인은 빈 문자열."""
    m = URL_RE.search(hint or "")
    if not m:
        return (hint or "").strip(), ""
    url = m.group(0).rstrip(".,)")
    text = (hint[:m.start()] + hint[m.end():]).strip(" ,;·")
    return text, normalize_domain(url)


class CandidateStore:
    """이메일 후보와 '실제로 목격된 도메인'을 기록하는 결정적 저장소.

    에이전트 실행 1회당 하나를 만들어 도구들과 공유한다. 최종 검증은
    이 저장소의 기록만 신뢰한다 (LLM 의 자기 보고는 검증에 쓰지 않음).
    """

    def __init__(self):
        self.sources = {}   # email -> {발견 도메인}

    def add(self, email, domain=""):
        e = (email or "").lower().rstrip(".")
        if not e or e.endswith(_ASSET_EXT) or _is_placeholder(e):
            return
        self.sources.setdefault(e, set())
        d = normalize_domain(domain)
        if d:
            self.sources[e].add(d)

    def add_from_text(self, text, domain=""):
        for e in _emails_from_text(text):
            self.add(e, domain)

    def all(self):
        return list(self.sources)

    def seen_on(self, email, domain):
        """이 이메일이 해당 도메인(또는 그 서브도메인) 페이지에서 실제 목격됐는가."""
        d = normalize_domain(domain)
        if not d:
            return False
        return any(s == d or s.endswith("." + d)
                   for s in self.sources.get((email or "").lower(), ()))


# ---------- 저수준 조회 (도구 내부에서 사용) ----------

def _fetch_page(url, timeout=8, headers=None):
    """페이지 HTML 을 직접 받는다 (macOS 인증서/한국 인코딩 폴백 포함)."""
    h = {"User-Agent": "Mozilla/5.0"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()
    except (ssl.SSLError, urllib.error.URLError) as e:
        if "SSL" not in str(e) and "certificate" not in str(e).lower():
            raise
        ctx = ssl._create_unverified_context()  # noqa: S323 - 공개 페이지 읽기 전용
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            data = r.read()
    for enc in ("utf-8", "euc-kr"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "ignore")


def _fetch_site_text(domain):
    """공식 사이트 홈 + 문의성 하위 페이지(최대 2개)의 HTML 을 합쳐 반환."""
    home = ""
    for scheme in ("https", "http"):
        try:
            home = _fetch_page(f"{scheme}://{domain}")
            break
        except Exception:  # noqa: BLE001 - 접속 실패 시 다음 스킴으로
            continue
    if not home:
        return ""
    texts = [home]
    picked = []
    for href in re.findall(r'href=["\x27]([^"\x27]+)["\x27]', home):
        if len(picked) >= 2 or not _CONTACT_LINK_RE.search(href):
            continue
        url = href if href.startswith("http") else f"https://{domain}/{href.lstrip('/')}"
        if domain in url and url not in picked:
            picked.append(url)
    for url in picked:
        try:
            texts.append(_fetch_page(url))
        except Exception:  # noqa: BLE001
            pass
    return "\n".join(texts)


class SearchQuotaError(RuntimeError):
    """Tavily 크레딧 소진/한도 초과. 재시도해도 소용없으니 배치를 멈춘다."""


# basic 1크레딧 / advanced 2크레딧. 실측상 결과 차이가 없어 basic 을 기본으로 둔다.
TAVILY_DEPTH = os.getenv("TAVILY_SEARCH_DEPTH", "basic")
_QUOTA_HINTS = ("432", "usage limit", "exceeds your plan", "quota",
                "credit", "401", "invalid api key")


def _tavily(query, domains=None):
    """Tavily 검색. 크레딧 소진은 SearchQuotaError 로 올려 조용히 묻히지 않게 한다.

    langchain_tavily 는 실패를 예외가 아니라 {"error": ...} 딕셔너리로 돌려준다.
    이걸 걸러내지 않으면 '검색 결과 0건'과 구분되지 않아, 크레딧이 떨어진 뒤에도
    앱이 정상 동작하는 것처럼 보이면서 전 업체가 '미발견'으로 기록된다.
    """
    tool_ = TavilySearch(max_results=8, include_answer=True,
                         search_depth=TAVILY_DEPTH, include_raw_content=True,
                         include_domains=domains)
    raw = tool_.invoke({"query": query})
    err = raw.get("error") if isinstance(raw, dict) else None
    if err:
        msg = str(err)
        if any(h in msg.lower() for h in _QUOTA_HINTS):
            raise SearchQuotaError(f"Tavily 크레딧/한도 문제: {msg}")
        raise RuntimeError(f"Tavily 오류: {msg}")
    return raw


def _results_list(raw):
    if isinstance(raw, dict):
        return raw.get("results", [])
    if isinstance(raw, list):
        return raw
    return []


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


def _scan_js_bundles(domain, home_html, max_files=5, max_bytes=2_000_000):
    """홈 HTML 의 <script src> 중 '동일 도메인 .js' 본문을 이어붙여 반환.

    SPA 번들 안에 이메일이 문자열로 박힌 경우를 대비한 최후 폴백.
    파일 개수·크기 상한으로 비용을 통제한다(성공/실패 무관하게 시도 횟수를 센다).
    """
    srcs = re.findall(
        r'<script[^>]+src=["\x27]([^"\x27]+\.js(?:\?[^"\x27]*)?)["\x27]',
        home_html or "", re.I)
    texts, count = [], 0
    for src in srcs:
        if count >= max_files:
            break
        if src.startswith("//"):
            src = "https:" + src
        url = src if src.startswith("http") else f"https://{domain}/{src.lstrip('/')}"
        if normalize_domain(url) != domain:
            continue
        count += 1                      # 동일 도메인 대상은 성공/실패 무관하게 계수
        try:
            texts.append(_fetch_page(url)[:max_bytes])
        except Exception:  # noqa: BLE001 - 개별 번들 실패는 건너뜀
            continue
    return "\n".join(texts)


def _extract_cands(text):
    """이메일 후보 리스트(에셋/플레이스홀더 제외, 순서 보존).

    Task 1 의 _emails_from_text(이중 패스 + 잘림 보정)를 재사용해 store 와
    동일한 추출 규칙을 쓴다(표시용 후보 목록과 grounding store 의 일관성).
    """
    out = []
    for e in _emails_from_text(text):
        if e.endswith(_ASSET_EXT) or _is_placeholder(e):
            continue
        out.append(e)
    return out


# ---------- 에이전트 도구 팩토리 ----------

def make_search_tools(store):
    """검색 에이전트용 도구 목록. 모든 결과의 이메일 후보를 store 에 기록한다."""

    @tool
    def web_search(query: str, include_domain: str = "") -> str:
        """웹을 검색해 결과 요약과 발견된 이메일 후보를 돌려준다.

        include_domain 에 'example.com' 처럼 도메인을 주면 그 도메인 안에서만
        검색한다 (공식 홈페이지에 게시된 이메일을 찾을 때 사용).
        """
        domains = [normalize_domain(include_domain)] if include_domain.strip() else None
        try:
            raw = _tavily(query, domains)
        except SearchQuotaError:
            raise            # 배치를 멈춰야 하므로 관찰로 삼키지 않고 올린다
        except Exception as e:  # noqa: BLE001 - 그 밖의 실패는 관찰로 반환
            return f"검색 실패: {e}"
        lines = []
        answer = raw.get("answer") if isinstance(raw, dict) else None
        if answer:
            store.add_from_text(answer, "")   # 출처 불명 → 도메인 없이 기록
            lines.append(f"[종합 답변] {answer}")
        found = []
        for r in _results_list(raw)[:8]:
            if not isinstance(r, dict):
                continue
            url = r.get("url", "")
            dom = normalize_domain(url)
            text = " ".join([r.get("title", ""), r.get("content", "") or "",
                             r.get("raw_content", "") or ""])
            store.add_from_text(text, dom)
            store.add_from_text(url, dom)
            result_emails = []
            for e in EMAIL_RE.findall(text + " " + url):
                e = e.lower().rstrip(".")
                if (not e.endswith(_ASSET_EXT) and not _is_placeholder(e)
                        and (e, dom) not in found):
                    found.append((e, dom))
                    result_emails.append(e)
            content = (r.get("raw_content") or r.get("content") or "")[:700]
            # Sanitize content to remove placeholder emails
            for e in EMAIL_RE.findall(content):
                e_lower = e.lower().rstrip(".")
                if _is_placeholder(e_lower):
                    content = content.replace(e, "")
            if result_emails or not EMAIL_RE.search(text + " " + url):
                lines.append(f"- {r.get('title', '')} ({url})\n  {content}")
        if found:
            lines.append("\n[이 검색에서 발견된 이메일 후보]")
            lines += [f"- {e}  (출처: {d or '불명'})" for e, d in found[:15]]
        else:
            lines.append("\n[이 검색에서 발견된 이메일 후보 없음]")
        return "\n".join(lines) if lines else "결과 없음"

    @tool
    def open_website(url_or_domain: str) -> str:
        """웹페이지(도메인 또는 URL)를 직접 열어 본문과 이메일 후보를 가져온다.

        정적 조회로 이메일 후보가 없으면 Jina Reader(JS 렌더링)로 재조회하고,
        그래도 없으면 홈의 동일 도메인 .js 번들까지 스캔한다(최후 폴백).
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
        if not cands and text:
            js = _scan_js_bundles(domain, text)
            if js:
                store.add_from_text(js, domain)
                bc = _extract_cands(js)
                if bc:
                    cands, used = bc, "bundle"
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

    return [web_search, open_website]


def make_research_tool():
    """답장 에이전트용 보조 검색 도구 (문의 답변에 필요한 정보 조사)."""

    @tool
    def web_search(query: str) -> str:
        """웹을 검색해 결과 요약을 돌려준다. 업체 문의에 답하기 위한 정보 조사용."""
        try:
            raw = _tavily(query)
        except Exception as e:  # noqa: BLE001
            return f"검색 실패: {e}"
        lines = []
        answer = raw.get("answer") if isinstance(raw, dict) else None
        if answer:
            lines.append(f"[종합 답변] {answer}")
        for r in _results_list(raw)[:5]:
            if isinstance(r, dict):
                lines.append(f"- {r.get('title', '')} ({r.get('url', '')})\n"
                             f"  {(r.get('content') or '')[:500]}")
        return "\n".join(lines) or "결과 없음"

    return web_search
