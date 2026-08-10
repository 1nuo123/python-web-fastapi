"""Git worktree 适配器路径测试。"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from src.core.worktree_contract.worktree_contract import GitWorktreePolicy
from src.infrastructure.worktree.git_worktree_adapter import GitWorktreeAdapter


class WorkspaceRootResolverFake:
    """返回测试仓库根。"""

    def __init__(self, root: Path) -> None:
        self.root = root

    def resolve_root(self, workspace_key: str, *, require_write: bool = False) -> Path:
        return self.root


class TestGitWorktreeAdapterPath:
    """验证 worktree 标识与路径边界。"""

    def test_worktreeId_whenContainsSeparator_shouldReject(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            adapter = GitWorktreeAdapter(WorkspaceRootResolverFake(Path(temporary_directory)))
            try:
                adapter._resolve_worktree_target(
                    Path(temporary_directory),
                    "..\\outside",
                )
            except PermissionError:
                pass
            else:
                raise AssertionError("包含路径分隔符的 worktree id 未被拒绝。")

    def test_worktreeId_whenEmptyThread_shouldBuildStableId(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            adapter = GitWorktreeAdapter(WorkspaceRootResolverFake(Path(temporary_directory)))
            identifier = adapter._build_worktree_id("///")
            assert identifier.startswith("thread-id-")

    def test_policy_whenMaxActiveIsBoundary_shouldKeepContract(self) -> None:
        policy = GitWorktreePolicy(enabled=True, max_active=128)
        assert policy.max_active == 128

    def test_list_whenManagedRootDoesNotExist_shouldUseRepositoryDisk(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        with TemporaryDirectory() as temporary_directory:
            repository_root = Path(temporary_directory)
            adapter = GitWorktreeAdapter(WorkspaceRootResolverFake(repository_root))
            monkeypatch.setattr(adapter, "_run_git", TestGitWorktreeAdapterPath._empty_git_result)

            result = adapter.list("workspace")

            assert result.items == ()
            assert result.active_count == 0
            assert result.pending_cleanup_count == 0
            assert result.disk_used_percent is not None
            assert 0 <= result.disk_used_percent <= 100

    def test_list_whenRepositoryDoesNotExist_shouldRejectWorkspace(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            missing_root = Path(temporary_directory) / "missing"
            adapter = GitWorktreeAdapter(WorkspaceRootResolverFake(missing_root))

            with pytest.raises(FileNotFoundError):
                adapter.list("workspace")

    @staticmethod
    def _empty_git_result(root: Path, *arguments: str) -> str:
        return ""
