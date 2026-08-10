"""Codex 控制操作纯状态转换策略。"""

from src.domain.codex.host_status import CodexOperationStatus


class InvalidCodexOperationTransitionError(ValueError):
    """操作状态转换不满足冻结契约。"""


class CodexOperationStatePolicy:
    """校验操作状态只能沿允许边迁移。"""

    _allowed_targets: dict[CodexOperationStatus, frozenset[CodexOperationStatus]] = {
        CodexOperationStatus.PENDING: frozenset(
            {CodexOperationStatus.DISPATCHED, CodexOperationStatus.CANCELLED}
        ),
        CodexOperationStatus.DISPATCHED: frozenset(
            {
                CodexOperationStatus.ACKNOWLEDGED,
                CodexOperationStatus.TIMED_OUT,
                CodexOperationStatus.FAILED,
            }
        ),
        CodexOperationStatus.ACKNOWLEDGED: frozenset(
            {CodexOperationStatus.COMPLETED, CodexOperationStatus.FAILED}
        ),
        CodexOperationStatus.TIMED_OUT: frozenset(
            {
                CodexOperationStatus.DISPATCHED,
                CodexOperationStatus.ACKNOWLEDGED,
                CodexOperationStatus.COMPLETED,
                CodexOperationStatus.FAILED,
            }
        ),
        CodexOperationStatus.COMPLETED: frozenset(),
        CodexOperationStatus.FAILED: frozenset(),
        CodexOperationStatus.CANCELLED: frozenset(),
    }

    def validate_transition(
        self,
        current: CodexOperationStatus,
        target: CodexOperationStatus,
    ) -> None:
        """验证状态迁移，不执行持久化副作用。"""

        if target not in self._allowed_targets[current]:
            raise InvalidCodexOperationTransitionError(
                f"Codex 操作状态不允许从 {current.value} 转为 {target.value}。"
            )
