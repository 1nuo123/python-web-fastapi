"""Codex 审批纯状态转换策略。"""

from src.domain.codex.host_status import CodexApprovalState


class InvalidCodexApprovalTransitionError(ValueError):
    """审批状态转换不满足冻结契约。"""


class CodexApprovalStatePolicy:
    """校验审批状态迁移以及 APPLIED 的精确语义。"""

    _allowed_targets: dict[CodexApprovalState, frozenset[CodexApprovalState]] = {
        CodexApprovalState.PENDING: frozenset(
            {
                CodexApprovalState.CLAIMED,
                CodexApprovalState.EXPIRED,
                CodexApprovalState.CANCELLED,
            }
        ),
        CodexApprovalState.CLAIMED: frozenset(
            {
                CodexApprovalState.APPLIED,
                CodexApprovalState.DELIVERY_FAILED,
                CodexApprovalState.EXPIRED,
            }
        ),
        CodexApprovalState.DELIVERY_FAILED: frozenset(
            {CodexApprovalState.CLAIMED, CodexApprovalState.EXPIRED}
        ),
        CodexApprovalState.APPLIED: frozenset(),
        CodexApprovalState.EXPIRED: frozenset(),
        CodexApprovalState.CANCELLED: frozenset(),
    }

    def validate_transition(
        self,
        current: CodexApprovalState,
        target: CodexApprovalState,
    ) -> None:
        """验证审批状态迁移，不虚构 App Server 二次确认。"""

        if target not in self._allowed_targets[current]:
            raise InvalidCodexApprovalTransitionError(
                f"Codex 审批状态不允许从 {current.value} 转为 {target.value}。"
            )
