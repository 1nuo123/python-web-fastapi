"""Windows Git CLI worktree 适配器。"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final, Protocol

from src.core.worktree_contract.worktree_contract import (
    GitWorktreeBindRequest,
    GitWorktreeCreateRequest,
    GitWorktreeListResult,
    GitWorktreeOperationResult,
    GitWorktreeRemoveRequest,
    GitWorktreeSnapshot,
    WorktreeCleanupReason,
    WorktreeLifecycleState,
)

WORKTREE_MARKER_FILENAME: Final = ".codex-worktree.json"
WORKTREE_LOCK_FILENAME: Final = ".codex-worktree.lock"
WORKTREE_DIRECTORY_NAME: Final = ".codex-worktrees"
WORKTREE_ID_PREFIX: Final = "thread-"
WORKTREE_ID_READABLE_LENGTH: Final = 64
WORKTREE_ID_DIGEST_LENGTH: Final = 16
WORKTREE_LOCK_TIMEOUT_SECONDS: Final = 15.0
WORKTREE_LOCK_RETRY_SECONDS: Final = 0.1
GIT_COMMAND_TIMEOUT_SECONDS: Final = 60
GIT_ERROR_MESSAGE_LIMIT: Final = 512
GitWorktreeSnapshotList = list[GitWorktreeSnapshot]


class WorkspaceRootResolverPort(Protocol):
    """按 workspace key 返回本机已授权仓库根。"""

    def resolve_root(self, workspace_key: str, *, require_write: bool = False) -> Path: ...


class GitWorktreeAdapter:
    """在受控仓库根内执行 argv 形式 Git worktree 命令。"""

    def __init__(self, workspace_roots: WorkspaceRootResolverPort) -> None:
        self._workspace_roots = workspace_roots

    def create(self, request: GitWorktreeCreateRequest) -> GitWorktreeOperationResult:
        """在仓库受管目录内创建隔离 worktree。"""

        if not request.policy.enabled:
            return GitWorktreeOperationResult(
                success=False,
                message="当前工作区未启用隔离工作树。",
            )
        repository_root = self._resolve_repository_root(
            request.workspace_key,
            require_write=True,
        )
        managed_root = self._resolve_managed_root(
            repository_root,
            request.policy.managed_root,
        )
        managed_root.mkdir(parents=True, exist_ok=True)
        self._verify_disk_watermark(managed_root, request.policy.disk_watermark_percent)
        worktree_id = self._build_worktree_id(request.thread_id)
        target = self._resolve_worktree_target(managed_root, worktree_id)
        with self._repository_lock(repository_root):
            existing = self._read_snapshot(target, managed_root)
            if existing is not None:
                return GitWorktreeOperationResult(
                    success=False,
                    snapshot=existing,
                    message="同一线程的隔离工作树已经存在。",
                )
            if target.exists():
                return GitWorktreeOperationResult(
                    success=False,
                    message="目标目录已存在且缺少受信任工作树标记。",
                )
            active_count = len(self._list_snapshots(managed_root))
            if active_count >= request.policy.max_active:
                return GitWorktreeOperationResult(
                    success=False,
                    message="工作树达到并发上限。",
                )
            self._run_git(
                repository_root,
                "worktree",
                "add",
                "--detach",
                str(target),
                request.policy.base_branch,
            )
            now = datetime.now(UTC)
            snapshot = GitWorktreeSnapshot(
                worktree_id=worktree_id,
                workspace_key=request.workspace_key,
                thread_id=request.thread_id,
                path=target,
                branch=request.policy.base_branch,
                state=WorktreeLifecycleState.ACTIVE,
                dirty=False,
                created_at=now,
                updated_at=now,
                cleanup_after=now + timedelta(seconds=request.policy.retention_seconds),
            )
            try:
                self._write_marker(target, snapshot)
            except OSError:
                self._remove_git_worktree(repository_root, target, force=True)
                raise
            return GitWorktreeOperationResult(success=True, snapshot=snapshot)

    def list(self, workspace_key: str) -> GitWorktreeListResult:
        """列出带本系统 marker 的受管 worktree。"""

        repository_root = self._resolve_repository_root(workspace_key)
        managed_root = self._resolve_managed_root(repository_root, None)
        snapshots = self._list_snapshots(managed_root)
        return self._build_list_result(repository_root, snapshots)

    def remove(self, request: GitWorktreeRemoveRequest) -> GitWorktreeOperationResult:
        """按 workspace 与稳定标识删除受管 worktree。"""

        repository_root = self._resolve_repository_root(
            request.workspace_key,
            require_write=True,
        )
        managed_root = self._resolve_managed_root(repository_root, None)
        target = self._resolve_worktree_target(managed_root, request.worktree_id)
        with self._repository_lock(repository_root):
            snapshot = self._read_snapshot(target, managed_root)
            if snapshot is None or snapshot.workspace_key != request.workspace_key:
                return GitWorktreeOperationResult(
                    success=False,
                    message="受管工作树不存在或标记不匹配。",
                )
            dirty_snapshot = snapshot.model_copy(
                update={"dirty": self._is_dirty(snapshot.path), "updated_at": datetime.now(UTC)}
            )
            if dirty_snapshot.dirty and not request.force:
                pending = self._mark_pending_cleanup(
                    dirty_snapshot,
                    WorktreeCleanupReason.USER_REQUEST,
                )
                return GitWorktreeOperationResult(
                    success=False,
                    snapshot=pending,
                    pending_cleanup=True,
                    message="工作树存在未提交修改，未执行自动强删。",
                )
            try:
                self._remove_git_worktree(
                    repository_root,
                    dirty_snapshot.path,
                    force=request.force,
                )
            except (OSError, RuntimeError):
                pending = self._mark_pending_cleanup(
                    dirty_snapshot,
                    WorktreeCleanupReason.USER_REQUEST,
                )
                return GitWorktreeOperationResult(
                    success=False,
                    snapshot=pending,
                    pending_cleanup=True,
                    message="工作树删除失败，已进入待清理状态。",
                )
            return GitWorktreeOperationResult(
                success=True,
                snapshot=dirty_snapshot.model_copy(
                    update={
                        "state": WorktreeLifecycleState.REMOVED,
                        "updated_at": datetime.now(UTC),
                        "cleanup_reason": WorktreeCleanupReason.USER_REQUEST,
                    }
                ),
            )

    def prune(self, workspace_key: str) -> GitWorktreeListResult:
        """清理过期且干净的 worktree，失败时保留 marker。"""

        repository_root = self._resolve_repository_root(workspace_key, require_write=True)
        managed_root = self._resolve_managed_root(repository_root, None)
        outcomes: list[GitWorktreeSnapshot] = []
        with self._repository_lock(repository_root):
            now = datetime.now(UTC)
            for snapshot in self._list_snapshots(managed_root):
                if snapshot.cleanup_after is None or snapshot.cleanup_after > now:
                    continue
                refreshed = snapshot.model_copy(
                    update={"dirty": self._is_dirty(snapshot.path), "updated_at": now}
                )
                if refreshed.dirty:
                    outcomes.append(
                        self._mark_pending_cleanup(
                            refreshed,
                            WorktreeCleanupReason.TTL_EXPIRED,
                        )
                    )
                    continue
                try:
                    self._remove_git_worktree(repository_root, refreshed.path, force=False)
                except (OSError, RuntimeError):
                    outcomes.append(
                        self._mark_pending_cleanup(
                            refreshed,
                            WorktreeCleanupReason.TTL_EXPIRED,
                        )
                    )
                    continue
                outcomes.append(
                    refreshed.model_copy(
                        update={
                            "state": WorktreeLifecycleState.REMOVED,
                            "cleanup_reason": WorktreeCleanupReason.TTL_EXPIRED,
                        }
                    )
                )
        return self._build_list_result(repository_root, outcomes)

    def find_by_thread(
        self,
        workspace_key: str,
        thread_id: str,
    ) -> GitWorktreeSnapshot | None:
        """按上游 thread 查找仍可使用的 worktree。"""

        for snapshot in self.list(workspace_key).items:
            if snapshot.thread_id == thread_id and snapshot.state == WorktreeLifecycleState.ACTIVE:
                return snapshot
        return None

    def bind_thread(self, request: GitWorktreeBindRequest) -> GitWorktreeOperationResult:
        """将临时创建标识替换为 App Server 返回的上游 thread id。"""

        repository_root = self._resolve_repository_root(
            request.workspace_key,
            require_write=True,
        )
        managed_root = self._resolve_managed_root(repository_root, None)
        target = self._resolve_worktree_target(managed_root, request.worktree_id)
        with self._repository_lock(repository_root):
            snapshot = self._read_snapshot(target, managed_root)
            if snapshot is None or snapshot.workspace_key != request.workspace_key:
                return GitWorktreeOperationResult(
                    success=False,
                    message="受管工作树不存在或标记不匹配。",
                )
            bound = snapshot.model_copy(
                update={"thread_id": request.thread_id, "updated_at": datetime.now(UTC)}
            )
            self._write_marker(target, bound)
            return GitWorktreeOperationResult(success=True, snapshot=bound)

    def _resolve_repository_root(
        self,
        workspace_key: str,
        *,
        require_write: bool = False,
    ) -> Path:
        root = self._workspace_roots.resolve_root(
            workspace_key,
            require_write=require_write,
        ).resolve(strict=True)
        self._run_git(root, "rev-parse", "--show-toplevel")
        return root

    def _build_list_result(
        self,
        repository_root: Path,
        snapshots: GitWorktreeSnapshotList,
    ) -> GitWorktreeListResult:
        usage = shutil.disk_usage(repository_root)
        disk_used_percent = ((usage.total - usage.free) * 100) // usage.total
        return GitWorktreeListResult(
            items=tuple(snapshots),
            active_count=sum(item.state == WorktreeLifecycleState.ACTIVE for item in snapshots),
            pending_cleanup_count=sum(
                item.state == WorktreeLifecycleState.PENDING_CLEANUP for item in snapshots
            ),
            disk_used_percent=disk_used_percent,
        )

    def _resolve_managed_root(self, repository_root: Path, configured: Path | None) -> Path:
        candidate = (configured or repository_root / WORKTREE_DIRECTORY_NAME).resolve()
        if candidate == repository_root or not candidate.is_relative_to(repository_root):
            raise PermissionError("worktree managed root必须位于仓库根目录内。")
        return candidate

    def _resolve_worktree_target(self, managed_root: Path, worktree_id: str) -> Path:
        if Path(worktree_id).name != worktree_id:
            raise PermissionError("worktree id不得包含路径分隔符。")
        target = (managed_root / worktree_id).resolve()
        if target == managed_root or not target.is_relative_to(managed_root):
            raise PermissionError("worktree目录逃出受管根目录。")
        return target

    def _build_worktree_id(self, thread_id: str) -> str:
        readable = "".join(
            character if character.isalnum() or character == "-" else "-" for character in thread_id
        ).strip("-")[:WORKTREE_ID_READABLE_LENGTH]
        digest = hashlib.sha256(thread_id.encode("utf-8")).hexdigest()[:WORKTREE_ID_DIGEST_LENGTH]
        readable_prefix = readable or "id"
        return f"{WORKTREE_ID_PREFIX}{readable_prefix}-{digest}"

    def _list_snapshots(self, managed_root: Path) -> GitWorktreeSnapshotList:
        if not managed_root.exists():
            return []
        snapshots: list[GitWorktreeSnapshot] = []
        for marker in managed_root.glob(f"*/{WORKTREE_MARKER_FILENAME}"):
            snapshot = self._read_snapshot(marker.parent, managed_root)
            if snapshot is None:
                continue
            dirty = self._is_dirty(snapshot.path)
            snapshots.append(
                snapshot.model_copy(update={"dirty": dirty, "updated_at": datetime.now(UTC)})
            )
        return sorted(snapshots, key=lambda item: item.created_at)

    def _read_snapshot(
        self,
        target: Path,
        managed_root: Path,
    ) -> GitWorktreeSnapshot | None:
        marker = target / WORKTREE_MARKER_FILENAME
        if not marker.is_file():
            return None
        try:
            snapshot = GitWorktreeSnapshot.model_validate_json(marker.read_text(encoding="utf-8"))
            snapshot_path = snapshot.path.resolve(strict=False)
            target_path = target.resolve(strict=False)
        except (OSError, ValueError):
            return None
        if snapshot_path != target_path or not target_path.is_relative_to(managed_root):
            return None
        return snapshot

    def _is_dirty(self, path: Path) -> bool:
        if not path.is_dir():
            return True
        try:
            result = self._run_git(path, "status", "--porcelain")
        except RuntimeError:
            return True
        relevant_lines = [
            line
            for line in result.splitlines()
            if not line.endswith(WORKTREE_MARKER_FILENAME)
            and not line.endswith(f"{WORKTREE_MARKER_FILENAME}.tmp")
        ]
        return bool(relevant_lines)

    def _mark_pending_cleanup(
        self,
        snapshot: GitWorktreeSnapshot,
        reason: WorktreeCleanupReason,
    ) -> GitWorktreeSnapshot:
        pending = snapshot.model_copy(
            update={
                "state": WorktreeLifecycleState.PENDING_CLEANUP,
                "cleanup_reason": reason,
                "updated_at": datetime.now(UTC),
            }
        )
        self._write_marker(snapshot.path, pending)
        return pending

    def _write_marker(self, path: Path, snapshot: GitWorktreeSnapshot) -> None:
        marker = path / WORKTREE_MARKER_FILENAME
        temporary_marker = path / f"{WORKTREE_MARKER_FILENAME}.tmp"
        temporary_marker.write_text(snapshot.model_dump_json(), encoding="utf-8")
        temporary_marker.replace(marker)

    def _remove_git_worktree(
        self,
        repository_root: Path,
        target: Path,
        *,
        force: bool,
    ) -> None:
        marker = target / WORKTREE_MARKER_FILENAME
        marker_content: str | None = None
        if marker.is_file():
            marker_content = marker.read_text(encoding="utf-8")
            marker.unlink()
        arguments = ["worktree", "remove"]
        if force:
            arguments.append("--force")
        arguments.append(str(target))
        try:
            self._run_git(repository_root, *arguments)
        except (OSError, RuntimeError, subprocess.SubprocessError):
            if marker_content is not None and target.is_dir():
                marker.write_text(marker_content, encoding="utf-8")
            raise
        if target.exists():
            try:
                target.rmdir()
            except OSError as exc:
                raise RuntimeError("Git已移除工作树，但目录仍被占用。") from exc

    def _verify_disk_watermark(self, managed_root: Path, watermark_percent: int) -> None:
        usage = shutil.disk_usage(managed_root)
        used_percent = ((usage.total - usage.free) * 100) // usage.total
        if used_percent >= watermark_percent:
            raise OSError("磁盘使用率达到工作树创建水位。")

    def _run_git(self, cwd: Path, *arguments: str) -> str:
        completed = subprocess.run(
            ["git", "-C", str(cwd), *arguments],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=GIT_COMMAND_TIMEOUT_SECONDS,
            shell=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"Git工作树操作失败：{completed.stderr[:GIT_ERROR_MESSAGE_LIMIT]}")
        return completed.stdout

    class _RepositoryLock:
        """基于独占创建的跨进程仓库锁。"""

        def __init__(self, path: Path) -> None:
            self._path = path
            self._handle: int | None = None

        def __enter__(self) -> GitWorktreeAdapter._RepositoryLock:
            deadline = time.monotonic() + WORKTREE_LOCK_TIMEOUT_SECONDS
            while self._handle is None and time.monotonic() < deadline:
                try:
                    self._handle = os.open(
                        self._path,
                        os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    )
                except FileExistsError:
                    time.sleep(WORKTREE_LOCK_RETRY_SECONDS)
            if self._handle is None:
                raise TimeoutError("仓库工作树锁获取超时。")
            return self

        def __exit__(self, *_: object) -> None:
            if self._handle is not None:
                os.close(self._handle)
                self._path.unlink(missing_ok=True)
                self._handle = None

    def _repository_lock(self, repository_root: Path) -> GitWorktreeAdapter._RepositoryLock:
        return self._RepositoryLock(repository_root / WORKTREE_LOCK_FILENAME)
