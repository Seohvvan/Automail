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


def test_adjacent_emails_in_separate_tags_both_kept():
    s = CandidateStore()
    s.add_from_text("<td>a@x.com</td><td>b@y.com</td>", "z.com")
    assert "a@x.com" in s.all()
    assert "b@y.com" in s.all()
