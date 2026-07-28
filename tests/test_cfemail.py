"""Cloudflare 이메일 난독화(data-cfemail) 복원 테스트."""
from agents.tools import (CandidateStore, _cf_emails, _decode_cfemail,
                          _emails_from_text)

# farmtc365.com 실제 값 (data-cfemail → farmtc365@naver.com)
CF_HEX = "f09691829d8493c3c6c5b09e91869582de939f9d"


def test_decode_cfemail_known_value():
    assert _decode_cfemail(CF_HEX) == "farmtc365@naver.com"


def test_cf_emails_from_data_attr():
    html = f'<a class="__cf_email__" data-cfemail="{CF_HEX}">[email protected]</a>'
    assert _cf_emails(html) == ["farmtc365@naver.com"]


def test_cf_emails_from_protection_link():
    html = f'<a href="/cdn-cgi/l/email-protection#{CF_HEX}">[email protected]</a>'
    assert _cf_emails(html) == ["farmtc365@naver.com"]


def test_emails_from_text_recovers_cloudflare():
    # 텍스트엔 '[email protected]' 만 남아도 data-cfemail 로 원래 주소 회수
    html = f'<span>이메일 문의</span><a data-cfemail="{CF_HEX}">[email protected]</a>'
    assert "farmtc365@naver.com" in _emails_from_text(html)


def test_store_records_cfemail_with_domain():
    # 공식 도메인에서 목격된 것으로 기록되어야 grounding(HIGH)이 가능
    s = CandidateStore()
    s.add_from_text(f'<a data-cfemail="{CF_HEX}">[email protected]</a>', "farmtc365.com")
    assert "farmtc365@naver.com" in s.all()
    assert s.seen_on("farmtc365@naver.com", "farmtc365.com")


def test_invalid_cfemail_is_ignored():
    assert _decode_cfemail("zz") == ""              # 16진 아님 → 크래시 없이 ""
    assert _cf_emails('<a data-cfemail="zz">x</a>') == []
