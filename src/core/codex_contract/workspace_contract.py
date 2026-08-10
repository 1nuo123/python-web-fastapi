"""Codex 工作区公共契约。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.core.worktree_contract.worktree_contract import (
    WORKTREE_DEFAULT_BASE_BRANCH,
    WORKTREE_DEFAULT_DISK_WATERMARK_PERCENT,
    WORKTREE_DEFAULT_MAX_ACTIVE,
    WORKTREE_DEFAULT_RETENTION_SECONDS,
    WORKTREE_MAXIMUM_ACTIVE,
    WORKTREE_MAXIMUM_DISK_WATERMARK_PERCENT,
    WORKTREE_MAXIMUM_RETENTION_SECONDS,
    GitWorktreePolicy,
)


class CodexWorkspaceWorktreePolicyUpdate(BaseModel):
    """浏览器可修改的 worktree 策略字段。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = False
    base_branch: str = Field(
        default=WORKTREE_DEFAULT_BASE_BRANCH,
        min_length=1,
        max_length=256,
    )
    max_active: int = Field(
        default=WORKTREE_DEFAULT_MAX_ACTIVE,
        ge=1,
        le=WORKTREE_MAXIMUM_ACTIVE,
    )
    retention_seconds: int = Field(
        default=WORKTREE_DEFAULT_RETENTION_SECONDS,
        gt=0,
        le=WORKTREE_MAXIMUM_RETENTION_SECONDS,
    )
    disk_watermark_percent: int = Field(
        default=WORKTREE_DEFAULT_DISK_WATERMARK_PERCENT,
        ge=1,
        le=WORKTREE_MAXIMUM_DISK_WATERMARK_PERCENT,
    )

    def to_policy(self, *, managed_root: Path | None = None) -> GitWorktreePolicy:
        """转换为内部 worktree 策略，不接受浏览器指定本机绝对路径。"""

        return GitWorktreePolicy(
            enabled=self.enabled,
            managed_root=managed_root,
            base_branch=self.base_branch,
            max_active=self.max_active,
            retention_seconds=self.retention_seconds,
            disk_watermark_percent=self.disk_watermark_percent,
        )


class CodexWorkspaceUpdateRequest(BaseModel):
    """工作区名称、启用状态与隔离策略的更新请求。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    display_name: str | None = Field(default=None, min_length=1, max_length=128)
    enabled: bool | None = None
    worktree_policy: CodexWorkspaceWorktreePolicyUpdate | None = None


class CodexWorkspaceSnapshot(BaseModel):
    """不暴露本机绝对路径的工作区快照。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    workspace_id: UUID
    host_id: UUID
    owner_subject_id: str = Field(min_length=1, max_length=128)
    agent_workspace_key: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=128)
    repo_fingerprint: str | None = Field(default=None, max_length=128)
    default_branch: str | None = Field(default=None, max_length=256)
    worktree_policy: GitWorktreePolicy = Field(default_factory=GitWorktreePolicy)
    enabled: bool
    created_at: datetime
    updated_at: datetime
    version: int = Field(ge=1)


class CodexWorkspaceCollection(BaseModel):
    """当前主体在指定主机下可见的工作区集合。"""

    model_config = ConfigDict(extra="forbid")

    items: list[CodexWorkspaceSnapshot]
