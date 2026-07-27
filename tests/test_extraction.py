from agents.tools import CandidateStore, _html_to_text, _emails_from_text


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


def test_adjacent_emails_in_separate_tags_both_kept():
    s = CandidateStore()
    s.add_from_text("<td>a@x.com</td><td>b@y.com</td>", "z.com")
    assert "a@x.com" in s.all()
    assert "b@y.com" in s.all()


def test_markup_split_does_not_leave_truncated_fragment():
    s = CandidateStore()
    s.add_from_text("책임자 luckyfresh<span>.</span>official@gmail.com", "x.com")
    assert "luckyfresh.official@gmail.com" in s.all()
    assert "official@gmail.com" not in s.all()   # 잘린 조각은 제거


def test_legit_suffix_email_not_dropped():
    # '.' 경계가 아니면(단순 접미사) 실제 이메일은 보존
    got = _emails_from_text("sales@acme.co 와 wholesales@acme.co")
    assert "sales@acme.co" in got
    assert "wholesales@acme.co" in got


def test_distinct_plaintext_emails_sharing_dot_suffix_both_kept():
    # HTML 없음: 우연히 '.' 경계 접미사를 공유하는 서로 다른 실제 이메일은 보존
    got = _emails_from_text("문의: info@a.com, 담당자: kim.info@a.com")
    assert "info@a.com" in got
    assert "kim.info@a.com" in got
