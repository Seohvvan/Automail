"""A2 상태 배선 검증: WorkflowState 에 _stop 필드가 존재하는지 확인.

stop→finish 동작 자체는 Task 6 의 resolve_next_action 테스트가 커버한다.
"""
from agents.state import WorkflowState


def test_state_has_stop_field():
    assert "_stop" in WorkflowState.__annotations__
