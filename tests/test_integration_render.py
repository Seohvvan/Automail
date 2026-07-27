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
