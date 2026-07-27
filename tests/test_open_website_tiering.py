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


def test_scan_js_bundles_same_domain_only(monkeypatch):
    home = ('<script src="/assets/app.js"></script>'
            '<script src="https://cdn.other.com/vendor.js"></script>')
    calls = []

    def fake_fetch(url, timeout=8, headers=None):
        calls.append(url)
        return "footer email: farmtc365@naver.com"

    monkeypatch.setattr(tools, "_fetch_page", fake_fetch)
    js = tools._scan_js_bundles("farmtc365.com", home)
    assert "farmtc365@naver.com" in js
    assert not any("cdn.other.com" in u for u in calls)   # 외부 도메인은 fetch 안 함
    assert any("/assets/app.js" in u for u in calls)


def test_scan_js_bundles_respects_max_files(monkeypatch):
    # 동일 도메인 .js 가 많고 모두 실패해도 시도 횟수는 max_files 로 제한
    home = "".join(f'<script src="/a{i}.js"></script>' for i in range(10))
    calls = []

    def failing_fetch(url, timeout=8, headers=None):
        calls.append(url)
        raise OSError("boom")

    monkeypatch.setattr(tools, "_fetch_page", failing_fetch)
    tools._scan_js_bundles("z.com", home, max_files=3)
    assert len(calls) == 3


def test_scan_js_bundles_matches_versioned_src(monkeypatch):
    home = '<script src="/assets/app.js?v=2"></script>'
    calls = []
    monkeypatch.setattr(tools, "_fetch_page",
                        lambda url, **kw: calls.append(url) or "m@z.com")
    js = tools._scan_js_bundles("z.com", home)
    assert calls and calls[0].endswith("/assets/app.js?v=2")
    assert "m@z.com" in js


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
