from agents.search_agent import _SYSTEM, SearchDecision


def test_system_prompt_has_no_synthesis_rule():
    assert "임의 합성 금지" in _SYSTEM
    assert "유사 상호" in _SYSTEM or "유사 상호명" in _SYSTEM


def test_is_target_business_field_mentions_mismatch():
    desc = SearchDecision.model_fields["is_target_business"].description
    assert "불일치" in desc
