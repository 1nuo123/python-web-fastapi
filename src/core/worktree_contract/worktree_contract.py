"""可选 Git worktree 隔离的强类型契约。"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

WORKTREE_DEFAULT_BASE_BRANCH: Final = "HEAD"
WORKTREE_DEFAULT_MAX_ACTIVE: Final = 4
WORKTREE_MINIMUM_ACTIVE: Final = 1
WORKTREE_MAXIMUM_ACTIVE: Final = 128
WORKTREE_DEFAULT_RETENTION_SECONDS: Final = 604_800
WORKTREE_MAXIMUM_RETENTION_SECONDS: Final = 31_536_000
WORKTREE_DEFAULT_DISK_WATERMARK_PERCENT: Final = 85
WORKTREE_MINIMUM_DISK_WATERMARK_PERCENT: Final = 1
WORKTREE_MAXIMUM_DISK_WATERMARK_PERCENT: Final = 99
WORKTREE_MAXIMUM_PERCENT: Final = 100
WORKTREE_KEY_MAXIMUM_LENGTH: Final = 128
WORKTREE_THREAD_ID_MAXIMUM_LENGTH: Final = 256


class WorktreeLifecycleState(StrEnum):
    """worktree 生命周期状态。"""

    ACTIVE = "active"
    ARCHIVED = "archived"
    PENDING_CLEANUP = "pending_cleanup"
    REMOVED = "removed"


class WorktreeCleanupReason(StrEnum):
    """清理原因。"""

    USER_REQUEST = "user_request"
    TTL_EXPIRED = "ttl_expired"
    CAPACITY = "capacity"
    DISK_PRESSURE = "disk_pressure"


class GitWorktreePolicy(BaseModel):
    """工作区隔离策略，默认关闭。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = False
    managed_root: Path | None = None
    base_branch: str = Field(
        default=WORKTREE_DEFAULT_BASE_BRANCH,
        min_length=1,
        max_length=WORKTREE_THREAD_ID_MAXIMUM_LENGTH,
    )
    max_active: int = Field(
        default=WORKTREE_DEFAULT_MAX_ACTIVE,
        ge=WORKTREE_MINIMUM_ACTIVE,
        le=WORKTREE_MAXIMUM_ACTIVE,
    )
    retention_seconds: int = Field(
        default=WORKTREE_DEFAULT_RETENTION_SECONDS,
        gt=0,
        le=WORKTREE_MAXIMUM_RETENTION_SECONDS,
    )
    disk_watermark_percent: int = Field(
        default=WORKTREE_DEFAULT_DISK_WATERMARK_PERCENT,
        ge=WORKTREE_MINIMUM_DISK_WATERMARK_PERCENT,
        le=WORKTREE_MAXIMUM_DISK_WATERMARK_PERCENT,
    )


class GitWorktreeCreateRequest(BaseModel):
    """创建 worktree 的受限参数；不接受命令字符串。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    workspace_key: str = Field(min_length=1, max_length=WORKTREE_KEY_MAXIMUM_LENGTH)
    thread_id: str = Field(min_length=1, max_length=WORKTREE_THREAD_ID_MAXIMUM_LENGTH)
    policy: GitWorktreePolicy


class GitWorktreeSnapshot(BaseModel):
    """控制面可审计的 worktree 摘要。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    worktree_id: str = Field(min_length=1, max_length=WORKTREE_KEY_MAXIMUM_LENGTH)
    workspace_key: str = Field(min_length=1, max_length=WORKTREE_KEY_MAXIMUM_LENGTH)
    thread_id: str = Field(min_length=1, max_length=WORKTREE_THREAD_ID_MAXIMUM_LENGTH)
    path: Path
    branch: str = Field(min_length=1, max_length=WORKTREE_THREAD_ID_MAXIMUM_LENGTH)
    state: WorktreeLifecycleState
    dirty: bool
    created_at: datetime
    updated_at: datetime
    retention_seconds: int = Field(default=WORKTREE_DEFAULT_RETENTION_SECONDS, gt=0)
    cleanup_after: datetime | None = None
    cleanup_reason: WorktreeCleanupReason | None = None


class GitWorktreeOperationResult(BaseModel):
    """worktree 操作结果与可观测清理状态。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    success: bool
    snapshot: GitWorktreeSnapshot | None = None
    pending_cleanup: bool = False
    message: str | None = None


class GitWorktreeListResult(BaseModel):
    """受控 worktree 列表。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    items: tuple[GitWorktreeSnapshot, ...]
    active_count: int = Field(default=0, ge=0)
    pending_cleanup_count: int = Field(default=0, ge=0)
    disk_used_percent: int | None = Field(
        default=None,
        ge=0,
        le=WORKTREE_MAXIMUM_PERCENT,
    )


class GitWorktreeRemoveRequest(BaseModel):
    """删除请求要求携带稳定 worktree 身份。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    workspace_key: str = Field(min_length=1, max_length=WORKTREE_KEY_MAXIMUM_LENGTH)
    worktree_id: str = Field(min_length=1, max_length=WORKTREE_KEY_MAXIMUM_LENGTH)
    force: bool = False
    require_archived: bool = False


class GitWorktreeBindRequest(BaseModel):
    """把创建阶段使用的稳定 worktree 绑定到上游 thread。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    workspace_key: str = Field(min_length=1, max_length=WORKTREE_KEY_MAXIMUM_LENGTH)
    worktree_id: str = Field(min_length=1, max_length=WORKTREE_KEY_MAXIMUM_LENGTH)
    thread_id: str = Field(min_length=1, max_length=WORKTREE_THREAD_ID_MAXIMUM_LENGTH)
