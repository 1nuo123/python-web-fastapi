"""Git worktree 适配器异常测试。"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from src.core.worktree_contract.worktree_contract import GitWorktreeCreateRequest, GitWorktreePolicy
from src.infrastructure.worktree.git_worktree_adapter import GitWorktreeAdapter


class WorkspaceRootResolverFake:
    """返回不存在仓库根。"""

    def __init__(self, root: Path) -> None:
        self.root = root

    def resolve_root(self, workspace_key: str, *, require_write: bool = False) -> Path:
        return self.root


class TestGitWorktreeAdapterException:
    """验证 Git 依赖失败时不伪造成功。"""

    def test_create_whenRepositoryIsUnavailable_shouldRaiseRuntimeError(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            adapter = GitWorktreeAdapter(WorkspaceRootResolverFake(Path(temporary_directory)))
            try:
                adapter.create(
                    GitWorktreeCreateRequest(
                        workspace_key="workspace",
                        thread_id="thread-1",
                        policy=GitWorktreePolicy(enabled=True),
                    )
                )
            except RuntimeError as exc:
                assert "Git" in str(exc)
            else:
                raise AssertionError("非 Git 目录被误报为成功。")
