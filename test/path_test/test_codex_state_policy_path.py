"""Codex 状态策略关键路径测试。"""

import pytest

from src.domain.codex.host_status import CodexOperationStatus
from src.domain.codex.operation_state_policy import (
    CodexOperationStatePolicy,
    InvalidCodexOperationTransitionError,
)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (CodexOperationStatus.PENDING, CodexOperationStatus.DISPATCHED),
        (CodexOperationStatus.DISPATCHED, CodexOperationStatus.TIMED_OUT),
        (CodexOperationStatus.TIMED_OUT, CodexOperationStatus.DISPATCHED),
        (CodexOperationStatus.TIMED_OUT, CodexOperationStatus.COMPLETED),
    ],
)
def test_operation_transition_when_recovery_path_should_succeed(
    current: CodexOperationStatus,
    target: CodexOperationStatus,
) -> None:
    CodexOperationStatePolicy().validate_transition(current, target)


def test_operation_transition_when_pending_completes_directly_should_fail() -> None:
    with pytest.raises(InvalidCodexOperationTransitionError):
        CodexOperationStatePolicy().validate_transition(
            CodexOperationStatus.PENDING,
            CodexOperationStatus.COMPLETED,
        )
