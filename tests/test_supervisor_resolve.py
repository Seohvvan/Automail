from types import SimpleNamespace

from agents.supervisor import (MAX_SEARCH_ATTEMPTS, pending_search_targets,
                               resolve_next_action)


def _co(**kw):
    base = {"name": "X", "email": "", "search_attempts": 0}
    base.update(kw)
    return base


def test_pending_targets_email_empty_attempts_left():
    comps = [_co(name="A", email="", search_attempts=1),
             _co(name="B", email="b@x.com", search_attempts=0),
             _co(name="C", email="", search_attempts=MAX_SEARCH_ATTEMPTS)]
    assert pending_search_targets(comps, MAX_SEARCH_ATTEMPTS) == [0]


def test_stop_forces_finish_even_with_pending():
    comps = [_co(name="A", email="", search_attempts=0)]
    d = SimpleNamespace(action="approve_send", targets=[0])
    assert resolve_next_action(d, comps, True, MAX_SEARCH_ATTEMPTS) == ("finish", [])


def test_approve_send_overridden_by_pending_search():
    # 초안 있는 승인 대상 + 아직 미발견(검색 잔여) 업체 공존
    comps = [_co(name="A", email="a@x.com", subject="s", search_attempts=0),
             _co(name="B", email="", search_attempts=1)]
    d = SimpleNamespace(action="approve_send", targets=[0])
    action, valid = resolve_next_action(d, comps, False, MAX_SEARCH_ATTEMPTS)
    assert action == "search"
    assert valid == [1]


def test_finish_overridden_by_pending_search():
    comps = [_co(name="B", email="", search_attempts=0)]
    d = SimpleNamespace(action="finish", targets=[])
    action, valid = resolve_next_action(d, comps, False, MAX_SEARCH_ATTEMPTS)
    assert action == "search"
    assert valid == [0]


def test_approve_send_allowed_when_no_pending():
    comps = [_co(name="A", email="a@x.com", subject="s", search_attempts=0),
             _co(name="B", email="", search_attempts=MAX_SEARCH_ATTEMPTS)]
    d = SimpleNamespace(action="approve_send", targets=[0])
    action, valid = resolve_next_action(d, comps, False, MAX_SEARCH_ATTEMPTS)
    assert action == "approve_send"
    assert valid == [0]
