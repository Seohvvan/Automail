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


def test_generic_business_localparts_not_flagged():
    # mail@/admin@/info@/user@ 는 실제 업체가 쓰는 주소일 수 있으므로 차단하지 않는다
    for e in ("mail@company.co.kr", "admin@realbiz.com",
              "info@realbiz.com", "user@realbiz.com"):
        assert not _is_placeholder(e)
