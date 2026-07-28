from agents.search_agent import _SYSTEM, SearchDecision


def test_system_prompt_has_no_synthesis_rule():
    assert "임의 합성 금지" in _SYSTEM
    assert "유사 상호" in _SYSTEM or "유사 상호명" in _SYSTEM


def test_is_target_business_field_mentions_mismatch():
    desc = SearchDecision.model_fields["is_target_business"].description
    assert "불일치" in desc


def test_system_prompt_requires_opening_candidate_domain():
    # 검색 스니펫만 보고 포기하지 말고 후보 공식 도메인을 open_website 로 열어보게 강제
    assert "반드시 한 번은" in _SYSTEM
    assert "open_website" in _SYSTEM


def test_system_prompt_forbids_repeating_same_query():
    assert "같은 검색어 반복 금지" in _SYSTEM
