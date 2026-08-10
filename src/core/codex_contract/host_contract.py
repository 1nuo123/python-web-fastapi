"""Codex 主机公共契约。"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.core.codex_contract.app_server_schema_manifest_contract import (
    AppServerCapabilityDetail,
)


class CodexSandboxMode(StrEnum):
    """允许展示的 App Server 沙箱模式。"""

    READ_ONLY = "read-only"
    WORKSPACE_WRITE = "workspace-write"
    DANGER_FULL_ACCESS = "danger-full-access"


class CodexApprovalPolicy(StrEnum):
    """允许展示的 App Server 审批策略。"""

    UNTRUSTED = "untrusted"
    ON_REQUEST = "on-request"
    NEVER = "never"


class CodexHostCompatibilityState(StrEnum):
    """主机兼容性展示状态。"""

    UNKNOWN = "unknown"
    COMPATIBLE = "compatible"
    READ_ONLY = "read_only"
    UPGRADE_REQUIRED = "upgrade_required"
    BLOCKED = "blocked"


class CodexHostUpdateState(StrEnum):
    """主机更新展示状态。"""

    UNKNOWN = "unknown"
    CURRENT = "current"
    AVAILABLE = "available"
    UPDATING = "updating"
    FAILED = "failed"


class CodexHostDoctorState(StrEnum):
    """最近一次 Agent doctor 结果状态。"""

    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    BLOCKED = "blocked"


class CodexHostCapabilities(BaseModel):
    """主机已协商的封闭 capability 明细。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    items: tuple[AppServerCapabilityDetail, ...] = ()
    model_ids: tuple[str, ...] = ()
    reasoning_efforts: tuple[str, ...] = ()
    sandbox_modes: tuple[CodexSandboxMode, ...] = (CodexSandboxMode.WORKSPACE_WRITE,)
    approval_policies: tuple[CodexApprovalPolicy, ...] = (CodexApprovalPolicy.UNTRUSTED,)


class CodexHostCompatibilityDetail(BaseModel):
    """主机兼容性强类型摘要。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    state: CodexHostCompatibilityState = CodexHostCompatibilityState.UNKNOWN
    reason_code: str | None = Field(default=None, max_length=128)


class CodexHostUpdateDetail(BaseModel):
    """Agent/Codex bundle 更新摘要。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    state: CodexHostUpdateState = CodexHostUpdateState.UNKNOWN
    channel: str = Field(default="stable", min_length=1, max_length=32)
    current_version: str | None = Field(default=None, max_length=64)
    target_version: str | None = Field(default=None, max_length=64)
    last_checked_at: datetime | None = None
    last_result: str | None = Field(default=None, max_length=128)
    security_deadline: datetime | None = None


class CodexHostDoctorDetail(BaseModel):
    """Agent doctor 脱敏摘要。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    state: CodexHostDoctorState = CodexHostDoctorState.UNKNOWN
    checked_at: datetime | None = None
    issue_codes: tuple[str, ...] = ()


class CodexHostSnapshot(BaseModel):
    """控制面持久化的主机脱敏快照。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    host_id: UUID
    owner_subject_id: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=128)
    platform: str = Field(min_length=1, max_length=64)
    agent_version: str | None = Field(default=None, max_length=64)
    codex_version: str | None = Field(default=None, max_length=64)
    agent_protocol_version: str | None = Field(default=None, max_length=64)
    app_server_schema_digest: str | None = Field(default=None, max_length=128)
    status: str = Field(min_length=1, max_length=32)
    capabilities: CodexHostCapabilities = Field(default_factory=CodexHostCapabilities)
    compatibility: CodexHostCompatibilityDetail = Field(
        default_factory=CodexHostCompatibilityDetail
    )
    update: CodexHostUpdateDetail = Field(default_factory=CodexHostUpdateDetail)
    doctor: CodexHostDoctorDetail = Field(default_factory=CodexHostDoctorDetail)
    last_seen_at: datetime | None = None
    revoked_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    version: int = Field(ge=1)


class CodexHostCollection(BaseModel):
    """当前主体可见的主机集合。"""

    model_config = ConfigDict(extra="forbid")

    items: list[CodexHostSnapshot]


class CodexHostRenameRequest(BaseModel):
    """主机重命名强类型请求。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    display_name: str = Field(min_length=1, max_length=128)


class CodexHostRevokeRequest(BaseModel):
    """主机撤销的增强授权请求。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    step_up_token: str = Field(min_length=32, max_length=512)
