"""受管 worktree 清理协调器。"""

from __future__ import annotations

from dataclasses import dataclass

from src.application.ports.git_worktree_port import GitWorktreePort
from src.core.worktree_contract.worktree_contract import (
    GitWorktreeListResult,
    WorktreeLifecycleState,
)


@dataclass(frozen=True, slots=True)
class WorktreeCleanupReport:
    """一次清理协调的摘要。"""

    removed_count: int
    pending_count: int
    inspected_count: int


class WorktreeCleanupReconciler:
    """按 workspace 调用受管清理，不触碰未知 marker 的目录。"""

    def __init__(self, worktree_port: GitWorktreePort) -> None:
        self._worktree_port = worktree_port

    def reconcile(self, workspace_key: str) -> WorktreeCleanupReport:
        """清理达到 TTL 的干净 worktree 并汇总待清理状态。"""

        result: GitWorktreeListResult = self._worktree_port.prune(workspace_key)
        removed_count = sum(item.state == WorktreeLifecycleState.REMOVED for item in result.items)
        pending_count = sum(
            item.state == WorktreeLifecycleState.PENDING_CLEANUP for item in result.items
        )
        return WorktreeCleanupReport(
            removed_count=removed_count,
            pending_count=pending_count,
            inspected_count=len(result.items),
        )
