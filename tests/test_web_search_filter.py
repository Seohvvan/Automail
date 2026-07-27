import agents.tools as tools


def test_web_search_candidate_list_excludes_placeholder(monkeypatch):
    monkeypatch.setattr(tools, "_tavily", lambda q, d=None: {
        "results": [{"url": "https://x.com", "title": "",
                     "content": "문의 example@company.com 또는 real@x.com"}]})
    store = tools.CandidateStore()
    web_search = {t.name: t for t in tools.make_search_tools(store)}["web_search"]
    out = web_search.invoke({"query": "x"})
    assert "real@x.com" in out
    assert "example@company.com" not in out          # 표시 목록에서도 placeholder 제외
    assert "example@company.com" not in store.all()   # store 에도 없어야 함
