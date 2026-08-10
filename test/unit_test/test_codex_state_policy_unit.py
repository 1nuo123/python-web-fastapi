"""Codex 状态策略单元测试。"""

import pytest

from src.domain.codex.approval_state_policy import (
    CodexApprovalStatePolicy,
    InvalidCodexApprovalTransitionError,
)
from src.domain.codex.host_status import CodexApprovalState, CodexOperationStatus
from src.domain.codex.operation_state_policy import (
    CodexOperationStatePolicy,
    InvalidCodexOperationTransitionError,
)


class TestCodexStatePolicy:
    def test_operation_transition_when_acknowledged_completes_should_succeed(self) -> None:
        CodexOperationStatePolicy().validate_transition(
            CodexOperationStatus.ACKNOWLEDGED,
            CodexOperationStatus.COMPLETED,
        )

    def test_operation_transition_when_terminal_restarts_should_fail(self) -> None:
        with pytest.raises(InvalidCodexOperationTransitionError):
            CodexOperationStatePolicy().validate_transition(
                CodexOperationStatus.COMPLETED,
                CodexOperationStatus.DISPATCHED,
            )

    def test_approval_transition_when_claimed_applies_should_succeed(self) -> None:
        CodexApprovalStatePolicy().validate_transition(
            CodexApprovalState.CLAIMED,
            CodexApprovalState.APPLIED,
        )

    def test_approval_transition_when_pending_applies_should_fail(self) -> None:
        with pytest.raises(InvalidCodexApprovalTransitionError):
            CodexApprovalStatePolicy().validate_transition(
                CodexApprovalState.PENDING,
                CodexApprovalState.APPLIED,
            )
