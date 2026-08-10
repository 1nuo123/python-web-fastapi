"""真实 Git worktree 集成测试。"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from src.core.worktree_contract.worktree_contract import (
    GitWorktreeBindRequest,
    GitWorktreeCreateRequest,
    GitWorktreePolicy,
    GitWorktreeRemoveRequest,
    WorktreeLifecycleState,
)
from src.infrastructure.worktree.git_worktree_adapter import (
    WORKTREE_MARKER_FILENAME,
    GitWorktreeAdapter,
)
from src.infrastructure.worktree.worktree_cleanup_reconciler import (
    WorktreeCleanupReconciler,
)


class WorkspaceRootResolverFake:
    """返回真实测试仓库根。"""

    def __init__(self, root: Path) -> None:
        self.root = root

    def resolve_root(self, workspace_key: str, *, require_write: bool = False) -> Path:
        return self.root


@dataclass(frozen=True, slots=True)
class DiskUsageFake:
    """磁盘容量探针返回值。"""

    total: int
    used: int
    free: int


class TestGitWorktreeAdapterIntegration:
    """验证真实 Git create/list/remove 与 dirty 保护。"""

    @staticmethod
    def _run_git(root: Path, *arguments: str) -> None:
        subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=True,
            capture_output=True,
            text=True,
        )

    @pytest.mark.integration
    def test_lifecycle_whenRealRepository_shouldCreateListAndRemove(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self._run_git(root, "init")
            (root / "README.md").write_text("初始化\n", encoding="utf-8")
            self._run_git(root, "add", "README.md")
            self._run_git(
                root,
                "-c",
                "user.email=test@example.invalid",
                "-c",
                "user.name=Codex Test",
                "commit",
                "-m",
                "init",
            )
            adapter = GitWorktreeAdapter(WorkspaceRootResolverFake(root))
            policy = GitWorktreePolicy(enabled=True, disk_watermark_percent=99)
            created = adapter.create(
                GitWorktreeCreateRequest(
                    workspace_key="workspace",
                    thread_id="thread-1",
                    policy=policy,
                )
            )
            assert created.success is True
            assert created.snapshot is not None
            listed = adapter.list("workspace")
            assert listed.active_count == 1
            removed = adapter.remove(
                GitWorktreeRemoveRequest(
                    workspace_key="workspace",
                    worktree_id=created.snapshot.worktree_id,
                )
            )
            assert removed.success is True
            assert removed.snapshot is not None
            assert removed.snapshot.state == WorktreeLifecycleState.REMOVED

    @pytest.mark.integration
    def test_list_whenRealRepositoryHasNoManagedRoot_shouldReturnEmptyResult(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self._run_git(root, "init")
            adapter = GitWorktreeAdapter(WorkspaceRootResolverFake(root))

            listed = adapter.list("workspace")

            assert listed.items == ()
            assert listed.active_count == 0
            assert listed.pending_cleanup_count == 0
            assert listed.disk_used_percent is not None
            assert 0 <= listed.disk_used_percent <= 100

    @pytest.mark.integration
    def test_remove_whenDirtyAndNotForced_shouldEnterPendingCleanup(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self._run_git(root, "init")
            (root / "README.md").write_text("初始化\n", encoding="utf-8")
            self._run_git(root, "add", "README.md")
            self._run_git(
                root,
                "-c",
                "user.email=test@example.invalid",
                "-c",
                "user.name=Codex Test",
                "commit",
                "-m",
                "init",
            )
            adapter = GitWorktreeAdapter(WorkspaceRootResolverFake(root))
            created = adapter.create(
                GitWorktreeCreateRequest(
                    workspace_key="workspace",
                    thread_id="thread-dirty",
                    policy=GitWorktreePolicy(enabled=True, disk_watermark_percent=99),
                )
            )
            assert created.snapshot is not None
            (created.snapshot.path / "changed.txt").write_text("未提交\n", encoding="utf-8")
            removed = adapter.remove(
                GitWorktreeRemoveRequest(
                    workspace_key="workspace",
                    worktree_id=created.snapshot.worktree_id,
                )
            )
            assert removed.success is False
            assert removed.pending_cleanup is True
            assert removed.snapshot is not None
            assert removed.snapshot.state == WorktreeLifecycleState.PENDING_CLEANUP
            forced = adapter.remove(
                GitWorktreeRemoveRequest(
                    workspace_key="workspace",
                    worktree_id=created.snapshot.worktree_id,
                    force=True,
                )
            )
            assert forced.success is True

    @pytest.mark.integration
    def test_bind_find_duplicate_capacity_and_prune_should_preserve_managed_boundaries(
        self,
    ) -> None:
        """验证绑定、查询、重复创建、容量和 TTL 清理使用同一受管 marker。"""

        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self._run_git(root, "init")
            (root / "README.md").write_text("初始化\n", encoding="utf-8")
            self._run_git(root, "add", "README.md")
            self._run_git(
                root,
                "-c",
                "user.email=test@example.invalid",
                "-c",
                "user.name=Codex Test",
                "commit",
                "-m",
                "init",
            )
            adapter = GitWorktreeAdapter(WorkspaceRootResolverFake(root))
            policy = GitWorktreePolicy(
                enabled=True,
                max_active=1,
                disk_watermark_percent=99,
            )
            request = GitWorktreeCreateRequest(
                workspace_key="workspace",
                thread_id="temporary-operation",
                policy=policy,
            )
            created = adapter.create(request)
            assert created.snapshot is not None

            duplicate = adapter.create(request)
            capacity = adapter.create(
                GitWorktreeCreateRequest(
                    workspace_key="workspace",
                    thread_id="second-operation",
                    policy=policy,
                )
            )
            bound = adapter.bind_thread(
                GitWorktreeBindRequest(
                    workspace_key="workspace",
                    worktree_id=created.snapshot.worktree_id,
                    thread_id="upstream-thread",
                )
            )
            found = adapter.find_by_thread("workspace", "upstream-thread")

            assert duplicate.success is False
            assert duplicate.snapshot is not None
            assert capacity.success is False
            assert bound.success is True
            assert bound.snapshot is not None
            assert found is not None
            assert found.thread_id == "upstream-thread"
            assert adapter.find_by_thread("workspace", "missing-thread") is None

            marker = created.snapshot.path / WORKTREE_MARKER_FILENAME
            expired = bound.snapshot.model_copy(
                update={
                    "cleanup_after": datetime.now(UTC) - timedelta(seconds=1),
                    "updated_at": datetime.now(UTC),
                }
            )
            marker.write_text(expired.model_dump_json(), encoding="utf-8")
            report = WorktreeCleanupReconciler(adapter).reconcile("workspace")

            assert report.inspected_count == 1
            assert report.removed_count == 1
            assert report.pending_count == 0
            assert adapter.list("workspace").active_count == 0
            missing_bind = adapter.bind_thread(
                GitWorktreeBindRequest(
                    workspace_key="workspace",
                    worktree_id=created.snapshot.worktree_id,
                    thread_id="missing",
                )
            )
            missing_remove = adapter.remove(
                GitWorktreeRemoveRequest(
                    workspace_key="workspace",
                    worktree_id=created.snapshot.worktree_id,
                )
            )
            assert missing_bind.success is False
            assert missing_remove.success is False

            untrusted_id = adapter._build_worktree_id("untrusted")  # noqa: SLF001
            untrusted_target = root / ".codex-worktrees" / untrusted_id
            untrusted_target.mkdir(parents=True)
            untrusted = adapter.create(
                GitWorktreeCreateRequest(
                    workspace_key="workspace",
                    thread_id="untrusted",
                    policy=policy,
                )
            )
            assert untrusted.success is False
            assert untrusted.snapshot is None

    @pytest.mark.integration
    def test_private_boundaries_should_detect_missing_path_invalid_marker_and_disk_watermark(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """验证 marker 损坏、缺失目录和磁盘水位均失败关闭。"""

        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self._run_git(root, "init")
            (root / "README.md").write_text("初始化\n", encoding="utf-8")
            self._run_git(root, "add", "README.md")
            self._run_git(
                root,
                "-c",
                "user.email=test@example.invalid",
                "-c",
                "user.name=Codex Test",
                "commit",
                "-m",
                "init",
            )
            adapter = GitWorktreeAdapter(WorkspaceRootResolverFake(root))
            managed_root = root / ".codex-worktrees"
            managed_root.mkdir()
            invalid_target = managed_root / "thread-invalid"
            invalid_target.mkdir()
            (invalid_target / WORKTREE_MARKER_FILENAME).write_text(
                "not-json",
                encoding="utf-8",
            )

            assert adapter._read_snapshot(invalid_target, managed_root) is None  # noqa: SLF001
            assert adapter._is_dirty(root / "missing") is True  # noqa: SLF001
            monkeypatch.setattr(
                "src.infrastructure.worktree.git_worktree_adapter.shutil.disk_usage",
                lambda _path: DiskUsageFake(total=100, used=100, free=0),
            )
            with pytest.raises(OSError, match="磁盘"):
                adapter.create(
                    GitWorktreeCreateRequest(
                        workspace_key="workspace",
                        thread_id="watermark",
                        policy=GitWorktreePolicy(
                            enabled=True,
                            disk_watermark_percent=99,
                        ),
                    )
                )
