from agents.sheet_sync import merge_email_column


def test_memory_value_wins():
    assert merge_email_column(["a@x.com"], [""]) == ["a@x.com"]


def test_empty_memory_preserves_sheet():
    # 재검색 실패로 메모리는 비었지만 시트에 사람이 넣은 값 → 보존
    assert merge_email_column([""], ["manual@x.com"]) == ["manual@x.com"]


def test_both_empty():
    assert merge_email_column([""], [""]) == [""]


def test_length_mismatch_sheet_shorter():
    assert merge_email_column(["a@x.com", ""], ["", "b@x.com"]) == ["a@x.com", "b@x.com"]


def test_length_mismatch_pads():
    assert merge_email_column(["a@x.com", ""], ["x@x.com"]) == ["a@x.com", ""]
