"""Git worktree 适配器单元测试。"""

from __future__ import annotations

import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from src.core.worktree_contract.worktree_contract import (
    GitWorktreeCreateRequest,
    GitWorktreePolicy,
    WorktreeLifecycleState,
)
from src.infrastructure.worktree.git_worktree_adapter import GitWorktreeAdapter


class WorkspaceRootResolverFake:
    """返回测试仓库根的最小替身。"""

    def __init__(self, root: Path) -> None:
        self.root = root

    def resolve_root(self, workspace_key: str, *, require_write: bool = False) -> Path:
        if workspace_key != "workspace":
            raise PermissionError("未知工作区。")
        return self.root


class TestGitWorktreeAdapterUnit:
    """验证适配器的纯契约分支。"""

    def test_create_when_disabled_shouldReturnBusinessFailure(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            adapter = GitWorktreeAdapter(WorkspaceRootResolverFake(root))
            result = adapter.create(
                GitWorktreeCreateRequest(
                    workspace_key="workspace",
                    thread_id="thread-1",
                    policy=GitWorktreePolicy(enabled=False),
                )
            )
            assert result.success is False
            assert result.snapshot is None

    def test_worktreePolicy_whenInvalidManagedRoot_shouldRejectContainment(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
            adapter = GitWorktreeAdapter(WorkspaceRootResolverFake(root))
            policy = GitWorktreePolicy(
                enabled=True,
                managed_root=root.parent / "outside",
            )
            try:
                adapter.create(
                    GitWorktreeCreateRequest(
                        workspace_key="workspace",
                        thread_id="thread-1",
                        policy=policy,
                    )
                )
            except PermissionError as exc:
                assert "managed root" in str(exc)
            else:
                raise AssertionError("仓库外 managed root 未被拒绝。")

    def test_cleanupState_whenPending_shouldRemainTyped(self) -> None:
        assert WorktreeLifecycleState.PENDING_CLEANUP.value == "pending_cleanup"
