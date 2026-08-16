"""控制面与 Windows Agent 的稳定产品协议。"""

from __future__ import annotations

from datetime import datetime
from typing import Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from src.core.codex_contract.agent_protocol_v2_contract import AgentEventDetail
from src.core.codex_contract.app_server_product_contract import (
    AppServerProductNotification,
)
from src.core.codex_contract.approval_contract import (
    CodexApprovalDisplaySummary,
    CodexApprovalKind,
    CodexApprovalRiskLevel,
)
from src.core.codex_contract.host_contract import CodexApprovalPolicy, CodexSandboxMode
from src.core.codex_contract.thread_contract import CodexThreadTitleSource

CODEX_AGENT_PROTOCOL_VERSION: Final = "1.0"
CODEX_AGENT_CONVERSATION_SNAPSHOT_SCHEMA_VERSION: Final = "1.0"


class CodexAgentHello(BaseModel):
    """Agent 建立设备认证连接后发送的版本与能力声明。"""

    model_config = ConfigDict(extra="forbid")

    host_id: UUID
    agent_version: str = Field(min_length=1, max_length=64)
    codex_version: str = Field(min_length=1, max_length=64)
    agent_protocol_version: str = Field(min_length=1, max_length=64)
    app_server_schema_digest: str = Field(min_length=64, max_length=128)
    capabilities: dict[str, JsonValue] = Field(default_factory=dict)


class CodexAgentHelloAck(BaseModel):
    """控制面接受 Agent 连接后返回的连接代次。"""

    model_config = ConfigDict(extra="forbid")

    host_id: UUID
    connection_epoch: int = Field(ge=1)
    heartbeat_seconds: int = Field(gt=0)


class CodexAgentHeartbeat(BaseModel):
    """Agent 心跳及本地 App Server 代次。"""

    model_config = ConfigDict(extra="forbid")

    host_id: UUID
    connection_epoch: int = Field(ge=1)
    app_server_instance_id: str = Field(min_length=1, max_length=128)
    sent_at: datetime


class CodexAgentCommand(BaseModel):
    """控制面提交后投递的稳定 Agent 命令。"""

    model_config = ConfigDict(extra="forbid")

    command_id: UUID
    operation_id: UUID
    host_id: UUID
    request_digest: str = Field(min_length=64, max_length=64)
    command_type: str = Field(min_length=1, max_length=64)
    params: dict[str, JsonValue] = Field(default_factory=dict)
    deadline: datetime
    sandbox_mode: CodexSandboxMode | None = None
    approval_policy: CodexApprovalPolicy | None = None
    expected_protocol_version: Literal["1.0"] = CODEX_AGENT_PROTOCOL_VERSION


class CodexAgentCommandAck(BaseModel):
    """Agent 对命令落盘、重放或待核对状态的确认。"""

    model_config = ConfigDict(extra="forbid")

    command_id: UUID
    operation_id: UUID
    state: str = Field(min_length=1, max_length=32)
    replayed: bool
    recovery_required: bool = False


class CodexAgentCommandResult(BaseModel):
    """命令结果；正文仅实时转发，不由本地账本保存。"""

    model_config = ConfigDict(extra="forbid")

    command_id: UUID
    operation_id: UUID
    outcome: Literal["completed", "failed", "unknown"]
    result: JsonValue | None = None
    error_code: str | None = Field(default=None, max_length=128)
    error_message: str | None = Field(default=None, max_length=512)


class CodexAgentRealtimeEvent(BaseModel):
    """从 App Server 映射出的实时事件。"""

    model_config = ConfigDict(extra="forbid")

    host_id: UUID
    app_server_instance_id: str = Field(min_length=1, max_length=128)
    occurred_at: datetime
    method: str = Field(min_length=1, max_length=128)
    params: JsonValue
    detail: AgentEventDetail | None = None
    product_notification: AppServerProductNotification | None = None


class CodexAgentApprovalOpened(BaseModel):
    """Agent 将 App Server server request 收窄后的审批事件。"""

    model_config = ConfigDict(extra="forbid")

    approval_id: UUID
    host_id: UUID
    app_server_instance_id: str = Field(min_length=1, max_length=128)
    approval_kind: CodexApprovalKind
    thread_id: str = Field(min_length=1, max_length=256)
    turn_id: str = Field(min_length=1, max_length=256)
    item_id: str = Field(min_length=1, max_length=256)
    risk_level: CodexApprovalRiskLevel
    payload_digest: str = Field(min_length=64, max_length=64)
    display_summary: CodexApprovalDisplaySummary
    expires_at: datetime


class CodexAgentWorkspaceSnapshot(BaseModel):
    """本地白名单工作区的脱敏声明。"""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=128)
    repo_fingerprint: str | None = Field(default=None, max_length=128)
    default_branch: str | None = Field(default=None, max_length=256)
    allow_write: bool


class AgentConversationSnapshotDetail(BaseModel):
    """Agent 仅向控制面发送的会话索引强类型扩展。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["conversation_snapshot"] = "conversation_snapshot"
    schema_version: Literal["1.0"] = CODEX_AGENT_CONVERSATION_SNAPSHOT_SCHEMA_VERSION
    thread_id: str = Field(min_length=1, max_length=256)
    workspace_key: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=256)
    title_source: CodexThreadTitleSource
    model_id: str | None = Field(default=None, max_length=128)
    model_provider: str | None = Field(default=None, max_length=128)
    status: str = Field(min_length=1, max_length=64)
    active_turn_id: str | None = Field(default=None, max_length=256)
    archived: bool
    source_kind: str | None = Field(default=None, max_length=64)
    created_at: datetime
    recency_at: datetime


class CodexAgentStateSnapshot(BaseModel):
    """Agent 重连后用于收敛控制面状态的权威快照。"""

    model_config = ConfigDict(extra="forbid")

    host_id: UUID
    app_server_instance_id: str = Field(min_length=1, max_length=128)
    workspaces: list[CodexAgentWorkspaceSnapshot]
    threads: list[AgentConversationSnapshotDetail]
    omitted_thread_workspace_keys: list[str] = Field(default_factory=list)
    pending_commands: list[dict[str, JsonValue]] = Field(default_factory=list)
    captured_at: datetime
