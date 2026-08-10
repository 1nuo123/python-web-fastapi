"""Git worktree 应用端口。"""

from __future__ import annotations

from typing import Protocol

from src.core.worktree_contract.worktree_contract import (
    GitWorktreeBindRequest,
    GitWorktreeCreateRequest,
    GitWorktreeListResult,
    GitWorktreeOperationResult,
    GitWorktreeRemoveRequest,
    GitWorktreeSnapshot,
)


class GitWorktreePort(Protocol):
    """仅提供 typed worktree 动作，不接受 shell 命令。"""

    def create(self, request: GitWorktreeCreateRequest) -> GitWorktreeOperationResult: ...

    def list(self, workspace_key: str) -> GitWorktreeListResult: ...

    def remove(self, request: GitWorktreeRemoveRequest) -> GitWorktreeOperationResult: ...

    def prune(self, workspace_key: str) -> GitWorktreeListResult: ...

    def find_by_thread(
        self,
        workspace_key: str,
        thread_id: str,
    ) -> GitWorktreeSnapshot | None: ...

    def bind_thread(self, request: GitWorktreeBindRequest) -> GitWorktreeOperationResult: ...
