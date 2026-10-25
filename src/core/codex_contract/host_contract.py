"""Codex 主机公共契约。"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Final, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.core.codex_contract.app_server_schema_manifest_contract import (
    AppServerCapabilityDetail,
)
from src.core.codex_contract.model_catalog_contract import CodexModelCatalog

CODEX_HOST_OBSERVATION_SCHEMA_VERSION: Final = "1.0"


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


class CodexHostObservationType(StrEnum):
    """不会改变用户配置版本的主机运行观测类型。"""

    HELLO = "hello"
    COMPATIBILITY = "compatibility"
    HEARTBEAT = "heartbeat"
    DISCONNECT = "disconnect"


class CodexHostCapabilities(BaseModel):
    """主机已协商的封闭 capability 明细。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    items: tuple[AppServerCapabilityDetail, ...] = ()
    app_server_instance_id: str | None = Field(default=None, max_length=128)
    model_catalog: CodexModelCatalog = Field(default_factory=CodexModelCatalog)
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


class CodexHostObservationHeader(BaseModel):
    """主机运行观测的公共定位头。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["codex_host_observation"] = "codex_host_observation"
    schema_version: Literal["1.0"] = CODEX_HOST_OBSERVATION_SCHEMA_VERSION
    detail_kind: CodexHostObservationType
    host_id: UUID
    owner_subject_id: str = Field(min_length=1, max_length=128)
    observed_at: datetime


class CodexHostObservationDetailBase(BaseModel):
    """主机运行观测强类型扩展字段基类。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = CODEX_HOST_OBSERVATION_SCHEMA_VERSION


class CodexHostHelloObservationDetail(CodexHostObservationDetailBase):
    """Agent hello 上报的运行时与能力快照。"""

    kind: Literal["hello"] = "hello"
    agent_version: str = Field(min_length=1, max_length=64)
    codex_version: str | None = Field(default=None, min_length=1, max_length=64)
    agent_protocol_version: str = Field(min_length=1, max_length=64)
    app_server_schema_digest: str | None = Field(default=None, min_length=1, max_length=128)
    capabilities: CodexHostCapabilities
    doctor: CodexHostDoctorDetail = Field(default_factory=CodexHostDoctorDetail)
    update: CodexHostUpdateDetail = Field(default_factory=CodexHostUpdateDetail)


class CodexHostCompatibilityObservationDetail(CodexHostObservationDetailBase):
    """Agent 与控制面协商后的兼容性观测。"""

    kind: Literal["compatibility"] = "compatibility"
    compatibility: CodexHostCompatibilityDetail


class CodexHostHeartbeatObservationDetail(CodexHostObservationDetailBase):
    """当前连接代次的在线心跳观测。"""

    kind: Literal["heartbeat"] = "heartbeat"
    app_server_instance_id: str | None = Field(default=None, min_length=1, max_length=128)


class CodexHostDisconnectObservationDetail(CodexHostObservationDetailBase):
    """权威连接释放后的离线观测。"""

    kind: Literal["disconnect"] = "disconnect"
    connection_started_at: datetime


CodexHostObservationDetail = Annotated[
    CodexHostHelloObservationDetail
    | CodexHostCompatibilityObservationDetail
    | CodexHostHeartbeatObservationDetail
    | CodexHostDisconnectObservationDetail,
    Field(discriminator="kind"),
]


class CodexHostObservation(BaseModel):
    """不增长 ``version`` 的主机运行观测信封。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    header: CodexHostObservationHeader
    detail: CodexHostObservationDetail

    @model_validator(mode="after")
    def validate_detail_identity(self) -> Self:
        """拒绝公共头与扩展字段类型或版本不一致。"""

        if self.header.detail_kind.value != self.detail.kind:
            raise ValueError("主机运行观测头与扩展类型不一致。")
        if self.header.schema_version != self.detail.schema_version:
            raise ValueError("主机运行观测头与扩展版本不一致。")
        return self


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
    connected: bool = False
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
