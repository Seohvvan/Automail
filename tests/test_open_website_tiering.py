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
