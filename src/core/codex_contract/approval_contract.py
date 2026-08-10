"""Codex 审批审计契约。"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CodexApprovalKind(StrEnum):
    """产品支持的审批类型。"""

    COMMAND = "command"
    FILE_CHANGE = "file_change"
    PERMISSIONS = "permissions"


class CodexApprovalRiskLevel(StrEnum):
    """审批的增强验证等级。"""

    NORMAL = "normal"
    HIGH = "high"


class CodexApprovalState(StrEnum):
    """审批审计状态。"""

    PENDING = "pending"
    CLAIMED = "claimed"
    APPLIED = "applied"
    DELIVERY_FAILED = "delivery_failed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class CodexApprovalDecision(StrEnum):
    """一次性审批决定。"""

    ACCEPT = "accept"
    DECLINE = "decline"
    CANCEL = "cancel"


class CodexApprovalDisplaySummary(BaseModel):
    """Agent 清洗后的审批展示字段，禁止包含原始 JSON 或绝对路径。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=256)
    workspace_name: str | None = Field(default=None, max_length=128)
    risk_level: CodexApprovalRiskLevel
    command_summary: str | None = Field(default=None, max_length=256)
    file_scope: tuple[str, ...] = Field(default=(), max_length=64)
    permission_names: tuple[str, ...] = Field(default=(), max_length=64)
    network_requested: bool = False
    extra_root_requested: bool = False


class CodexApprovalAuditSnapshot(BaseModel):
    """仅包含脱敏展示摘要的审批审计记录。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    approval_id: UUID
    owner_subject_id: str = Field(min_length=1, max_length=128)
    host_id: UUID
    workspace_id: UUID | None = None
    thread_id: str = Field(min_length=1, max_length=256)
    turn_id: str | None = Field(default=None, max_length=256)
    item_id: str | None = Field(default=None, max_length=256)
    approval_kind: CodexApprovalKind
    risk_level: CodexApprovalRiskLevel
    payload_digest: str = Field(min_length=64, max_length=64)
    display_summary: CodexApprovalDisplaySummary
    state: CodexApprovalState
    version: int = Field(ge=1)
    expires_at: datetime | None = None
    decided_by: str | None = Field(default=None, max_length=128)
    decision: CodexApprovalDecision | None = None
    decided_at: datetime | None = None
    applied_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class CodexApprovalCollection(BaseModel):
    """当前主体可见的审批摘要集合。"""

    model_config = ConfigDict(extra="forbid")

    items: list[CodexApprovalAuditSnapshot]


class CodexApprovalDecisionRequest(BaseModel):
    """基础一次性审批决定；会话级和额外权限不在此契约。"""

    model_config = ConfigDict(extra="forbid")

    decision: CodexApprovalDecision
    approval_version: int = Field(ge=1)
