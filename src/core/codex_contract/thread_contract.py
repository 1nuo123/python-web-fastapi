"""Codex 线程索引契约。"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CodexPlanStepStatus(StrEnum):
    """结构化计划步骤状态。"""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class CodexPlanStepSnapshot(BaseModel):
    """浏览器可直接渲染的计划步骤。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    step: str = Field(min_length=1, max_length=4_096)
    status: CodexPlanStepStatus


class CodexDiffChangeKind(StrEnum):
    """文件变更类型。"""

    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"


class CodexDiffLineKind(StrEnum):
    """Diff 行类型。"""

    CONTEXT = "context"
    ADDITION = "addition"
    DELETION = "deletion"


class CodexDiffLineSnapshot(BaseModel):
    """携带旧、新行号的单行 Diff。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: CodexDiffLineKind
    content: str = Field(max_length=4_096)
    old_line_number: int | None = Field(default=None, ge=1)
    new_line_number: int | None = Field(default=None, ge=1)


class CodexDiffHunkSnapshot(BaseModel):
    """一个可独立虚拟化的 Diff hunk。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    header: str = Field(min_length=1, max_length=512)
    old_start: int = Field(ge=0)
    new_start: int = Field(ge=0)
    lines: tuple[CodexDiffLineSnapshot, ...]


class CodexDiffFileSnapshot(BaseModel):
    """单文件结构化 Diff。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str = Field(min_length=1, max_length=1_024)
    old_path: str | None = Field(default=None, max_length=1_024)
    change_kind: CodexDiffChangeKind
    binary: bool
    large: bool
    truncated: bool
    hunks: tuple[CodexDiffHunkSnapshot, ...]


class CodexDiffSnapshot(BaseModel):
    """一次 turn 的结构化文件变更集合。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    files: tuple[CodexDiffFileSnapshot, ...]
    total_characters: int = Field(ge=0)
    truncated: bool


class CodexThreadIndexSnapshot(BaseModel):
    """控制面线程索引；不包含消息、代码或 Diff 正文。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    thread_index_id: UUID
    host_id: UUID
    workspace_id: UUID
    owner_subject_id: str = Field(min_length=1, max_length=128)
    upstream_thread_id: str = Field(min_length=1, max_length=256)
    display_name: str | None = Field(default=None, max_length=256)
    model: str | None = Field(default=None, max_length=128)
    reasoning_effort: str | None = Field(default=None, max_length=64)
    status: str = Field(min_length=1, max_length=32)
    active_turn_id: str | None = Field(default=None, max_length=256)
    archived: bool
    source_kind: str | None = Field(default=None, max_length=64)
    created_at: datetime | None = None
    updated_at: datetime
    last_synced_at: datetime


class CodexTurnSnapshot(BaseModel):
    """浏览器权威 thread snapshot 中的 turn。"""

    model_config = ConfigDict(extra="forbid")

    turn_id: str = Field(min_length=1, max_length=256)
    thread_id: str = Field(min_length=1, max_length=256)
    status: str = Field(min_length=1, max_length=32)
    started_at: str | None = None
    completed_at: str | None = None
    error_message: str | None = Field(default=None, max_length=512)


class CodexTimelineItemSnapshot(BaseModel):
    """稳定浏览器时间线条目，类型专用字段保持显式可空。"""

    model_config = ConfigDict(extra="forbid")

    item_id: str = Field(min_length=1, max_length=256)
    thread_id: str = Field(min_length=1, max_length=256)
    turn_id: str | None = Field(default=None, max_length=256)
    kind: str = Field(min_length=1, max_length=64)
    status: str = Field(min_length=1, max_length=32)
    created_at: str | None = None
    text: str | None = None
    explanation: str | None = None
    steps: tuple[CodexPlanStepSnapshot, ...] | None = None
    command: str | None = None
    output: str | None = None
    exit_code: int | None = None
    diff: CodexDiffSnapshot | None = None
    label: str | None = None
    detail: str | None = None


class CodexThreadAuthoritySnapshot(BaseModel):
    """App Server thread/read 正文与 PostgreSQL 所有权索引的组合响应。"""

    model_config = ConfigDict(extra="forbid")

    thread: CodexThreadIndexSnapshot
    turns: list[CodexTurnSnapshot]
    items: list[CodexTimelineItemSnapshot]
    history_status: Literal[
        "complete",
        "not_requested",
        "omitted_too_large",
        "not_available_yet",
    ] = "complete"
    next_history_cursor: str | None = Field(default=None, max_length=512)
