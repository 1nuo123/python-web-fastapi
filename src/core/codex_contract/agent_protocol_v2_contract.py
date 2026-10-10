"""Windows Agent protocol v2 公共头与强类型扩展字段契约。"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Final, Literal, cast
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    SerializerFunctionWrapHandler,
    model_serializer,
    model_validator,
)

from src.core.codex_contract.agent_command_contract import AgentCommandResultSummary
from src.core.codex_contract.app_server_product_contract import (
    APP_SERVER_PRODUCT_MAX_DELTA_CHARS,
    APP_SERVER_PRODUCT_MAX_TEXT_CHARS,
    AppServerPlanStep,
    AppServerProductTimelineItem,
    AppServerThreadProductSnapshot,
    AppServerThreadReadProductResult,
)
from src.core.codex_contract.app_server_schema_manifest_contract import (
    SHA256_HEX_PATTERN,
    AppServerCapabilityDetail,
    AppServerNotificationName,
)
from src.core.codex_contract.approval_contract import (
    CodexApprovalDisplaySummary as AgentApprovalDisplaySummary,
)
from src.core.codex_contract.agent_runtime_health_contract import AgentRuntimeStatus
from src.core.codex_contract.host_contract import CodexApprovalPolicy, CodexSandboxMode
from src.core.codex_contract.model_catalog_contract import (
    CodexModelCatalog,
    CodexEffectiveExecutionSettings,
)
from src.core.codex_contract.thread_contract import CodexThreadTitleSource
from src.core.worktree_contract.worktree_contract import GitWorktreePolicy
from src.core.codex_contract.workspace_contract import (
    ProjectExecutionSettingsApply,
    CodexWorkspaceExecutionPreferences,
)

AGENT_PROTOCOL_V2_KIND: Final = "codex_agent_protocol"
AGENT_PROTOCOL_V2_SCHEMA_VERSION: Final = "2.0"
AGENT_COMMAND_DETAIL_KIND_FIELD: Final = "kind"
AGENT_COMMAND_DETAIL_SCHEMA_VERSION_FIELD: Final = "schema_version"


class AgentProtocolMessageType(StrEnum):
    """v2 双向消息类型。"""

    HELLO = "hello"
    HELLO_ACK = "hello_ack"
    HEARTBEAT = "heartbeat"
    EXECUTION_LEASE = "execution_lease"
    EXECUTION_STOPPED = "execution_stopped"
    COMMAND = "command"
    COMMAND_ACK = "command_ack"
    COMMAND_RESULT = "command_result"
    EVENT_BATCH = "event_batch"
    EVENT_ACK = "event_ack"
    REPLAY_REQUEST = "replay_request"
    STATE_SNAPSHOT = "state_snapshot"


class AgentProtocolV2Header(BaseModel):
    """所有 v2 消息共享的稳定头字段。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["codex_agent_protocol"] = AGENT_PROTOCOL_V2_KIND
    schema_version: Literal["2.0"] = AGENT_PROTOCOL_V2_SCHEMA_VERSION
    message_id: UUID
    message_type: AgentProtocolMessageType
    detail_kind: AgentProtocolMessageType
    host_id: UUID
    key_id: UUID | None = None
    sent_at: datetime


class AgentProtocolV2DetailBase(BaseModel):
    """所有 Agent protocol v2 扩展字段共享的版本约束。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["2.0"] = AGENT_PROTOCOL_V2_SCHEMA_VERSION


class AgentHelloV2Detail(AgentProtocolV2DetailBase):
    """Agent 版本、schema 和 capability 声明。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["hello"] = "hello"
    execution_lease_supported: bool = False
    lease_request_id: UUID | None = None
    agent_version: str = Field(min_length=1, max_length=64)
    codex_version: str = Field(min_length=1, max_length=64)
    app_server_schema_digest: str = Field(pattern=SHA256_HEX_PATTERN)
    capabilities: tuple[AppServerCapabilityDetail, ...]
    model_ids: tuple[str, ...] = ()
    app_server_instance_id: str | None = Field(default=None, max_length=128)
    model_catalog: CodexModelCatalog = Field(default_factory=CodexModelCatalog)
    runtime_status: AgentRuntimeStatus | None = None
    reasoning_efforts: tuple[str, ...] = ()
    sandbox_modes: tuple[CodexSandboxMode, ...] = (CodexSandboxMode.WORKSPACE_WRITE,)
    approval_policies: tuple[CodexApprovalPolicy, ...] = (CodexApprovalPolicy.UNTRUSTED,)
    agent_event_epoch: UUID


class AgentHelloAckV2Detail(AgentProtocolV2DetailBase):
    """控制面握手确认与累计 ACK 起点。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["hello_ack"] = "hello_ack"
    connection_epoch: int = Field(ge=1)
    heartbeat_seconds: int = Field(gt=0)
    revocation_generation: int = Field(ge=0)
    acknowledged_event_epoch: UUID | None = None
    after_seq: int = Field(default=0, ge=0)


class AgentHeartbeatV2Detail(AgentProtocolV2DetailBase):
    """Agent 心跳与本地 App Server 代次。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["heartbeat"] = "heartbeat"
    lease_request_id: UUID | None = None
    connection_epoch: int = Field(ge=1)
    app_server_instance_id: UUID
    revocation_generation: int = Field(ge=0)


class AgentExecutionLeaseV2Detail(AgentProtocolV2DetailBase):
    """控制面确认账号执行资格；无确认时本机必须停止 Remote 执行。"""

    kind: Literal["execution_lease"] = "execution_lease"
    request_id: UUID | None = None
    generation: int = Field(ge=0)
    enabled: bool
    valid_for_seconds: int = Field(default=35, ge=1, le=60)


class AgentExecutionStoppedV2Detail(AgentProtocolV2DetailBase):
    kind: Literal["execution_stopped"] = "execution_stopped"
    generation: int = Field(ge=0)


class AgentCommandHeader(BaseModel):
    """所有 v2 command 共享的幂等与 deadline 字段。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    command_id: UUID
    operation_id: UUID
    request_digest: str = Field(pattern=SHA256_HEX_PATTERN)
    deadline: datetime
    execution_generation: int | None = Field(default=None, ge=0)


class AgentCommandDetailBase(AgentProtocolV2DetailBase):
    """只把原命令中真实存在的可选字段编码到 v2 帧。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    @model_serializer(mode="wrap")
    def serialize_present_fields(
        self,
        handler: SerializerFunctionWrapHandler,
    ) -> dict[str, JsonValue]:
        """保留可选字段的缺省语义，避免跨协议往返改变请求摘要。"""

        payload = cast(dict[str, JsonValue], handler(self))
        included_fields = self.model_fields_set | {
            AGENT_COMMAND_DETAIL_KIND_FIELD,
            AGENT_COMMAND_DETAIL_SCHEMA_VERSION_FIELD,
        }
        return {
            field_name: value
            for field_name, value in payload.items()
            if field_name in included_fields
        }


class AgentThreadListCommandDetail(AgentCommandDetailBase):
    """列出受限工作区线程。"""

    kind: Literal["thread.list"] = "thread.list"
    workspace_key: str = Field(min_length=1, max_length=128)
    limit: int = Field(default=50, ge=1, le=200)
    cursor: str | None = Field(default=None, max_length=512)


class AgentThreadReadCommandDetail(AgentCommandDetailBase):
    """读取一个已登记工作区线程。"""

    kind: Literal["thread.read"] = "thread.read"
    workspace_key: str = Field(min_length=1, max_length=128)
    thread_id: str = Field(min_length=1, max_length=256)
    include_turns: bool = True


class AgentThreadStartCommandDetail(AgentCommandDetailBase):
    """在受限工作区创建线程。"""

    kind: Literal["thread.start"] = "thread.start"
    workspace_key: str = Field(min_length=1, max_length=128)
    model: str | None = Field(default=None, min_length=1, max_length=128)
    sandbox_mode: CodexSandboxMode
    approval_policy: CodexApprovalPolicy
    worktree_policy: GitWorktreePolicy | None = None


class AgentThreadResumeCommandDetail(AgentCommandDetailBase):
    """恢复受限工作区线程。"""

    kind: Literal["thread.resume"] = "thread.resume"
    workspace_key: str = Field(min_length=1, max_length=128)
    thread_id: str = Field(min_length=1, max_length=256)
    sandbox_mode: CodexSandboxMode
    approval_policy: CodexApprovalPolicy


class AgentThreadNameSetCommandDetail(AgentCommandDetailBase):
    """设置会话手工标题。"""

    kind: Literal["thread.name_set"] = "thread.name_set"
    workspace_key: str = Field(min_length=1, max_length=128)
    thread_id: str = Field(min_length=1, max_length=256)
    display_name: str = Field(min_length=1, max_length=256)


class AgentThreadArchiveCommandDetail(AgentCommandDetailBase):
    """归档会话。"""

    kind: Literal["thread.archive"] = "thread.archive"
    workspace_key: str = Field(min_length=1, max_length=128)
    thread_id: str = Field(min_length=1, max_length=256)


class AgentThreadUnarchiveCommandDetail(AgentCommandDetailBase):
    """恢复归档会话。"""

    kind: Literal["thread.unarchive"] = "thread.unarchive"
    workspace_key: str = Field(min_length=1, max_length=128)
    thread_id: str = Field(min_length=1, max_length=256)


class AgentThreadCompactCommandDetail(AgentCommandDetailBase):
    """压缩已登记线程上下文。"""

    kind: Literal["thread.compact"] = "thread.compact"
    workspace_key: str = Field(min_length=1, max_length=128)
    thread_id: str = Field(min_length=1, max_length=256)


class AgentTurnStartCommandDetail(AgentCommandDetailBase):
    """向线程发送新的用户输入。"""

    kind: Literal["turn.start"] = "turn.start"
    workspace_key: str = Field(min_length=1, max_length=128)
    thread_id: str = Field(min_length=1, max_length=256)
    # 与 HTTP 幂等键同值，并原样映射为官方 clientUserMessageId。
    client_operation_id: UUID | None = None
    message: str = Field(min_length=1, max_length=200_000)
    model: str | None = Field(default=None, min_length=1, max_length=128)
    reasoning_effort: str | None = Field(default=None, min_length=1, max_length=64)
    sandbox_mode: CodexSandboxMode
    approval_policy: CodexApprovalPolicy


class AgentTurnSteerCommandDetail(AgentCommandDetailBase):
    """向活动 turn 注入后续用户输入。"""

    kind: Literal["turn.steer"] = "turn.steer"
    workspace_key: str = Field(min_length=1, max_length=128)
    thread_id: str = Field(min_length=1, max_length=256)
    turn_id: str = Field(min_length=1, max_length=256)
    client_operation_id: UUID | None = None
    message: str = Field(min_length=1, max_length=200_000)


class AgentTurnInterruptCommandDetail(AgentCommandDetailBase):
    """幂等中断活动 turn。"""

    kind: Literal["turn.interrupt"] = "turn.interrupt"
    workspace_key: str = Field(min_length=1, max_length=128)
    thread_id: str = Field(min_length=1, max_length=256)
    turn_id: str = Field(min_length=1, max_length=256)


class AgentApprovalReplyCommandDetail(AgentCommandDetailBase):
    """回复当前 App Server 代次中的审批。"""

    kind: Literal["approval.reply"] = "approval.reply"
    approval_id: UUID
    decision: Literal[
        "accept",
        "acceptForSession",
        "acceptWithExecpolicyAmendment",
        "applyNetworkPolicyAmendment",
        "decline",
        "cancel",
    ]
    approval_version: int = Field(ge=1)


class AgentWorkspaceSettingsCommandDetail(AgentCommandDetailBase):
    """只接受项目身份及类型化草稿，不接受本机路径或任意配置键。"""

    kind: Literal["workspace.settings"] = "workspace.settings"
    workspace_key: str = Field(min_length=1, max_length=128)
    settings: ProjectExecutionSettingsApply


AgentCommandDetail = Annotated[
    AgentThreadListCommandDetail
    | AgentThreadReadCommandDetail
    | AgentThreadStartCommandDetail
    | AgentThreadResumeCommandDetail
    | AgentThreadNameSetCommandDetail
    | AgentThreadArchiveCommandDetail
    | AgentThreadUnarchiveCommandDetail
    | AgentThreadCompactCommandDetail
    | AgentTurnStartCommandDetail
    | AgentTurnSteerCommandDetail
    | AgentTurnInterruptCommandDetail
    | AgentApprovalReplyCommandDetail
    | AgentWorkspaceSettingsCommandDetail,
    Field(discriminator="kind"),
]


class AgentCommandV2Detail(AgentProtocolV2DetailBase):
    """command 公共头与强类型扩展字段。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["command"] = "command"
    header: AgentCommandHeader
    detail: AgentCommandDetail

    @model_validator(mode="after")
    def validate_detail_identity(self) -> AgentCommandV2Detail:
        """命令扩展版本必须与命令信封一致。"""

        if self.schema_version != self.detail.schema_version:
            raise ValueError("Agent命令信封与扩展版本不一致。")
        return self


class AgentCommandAckV2Detail(AgentProtocolV2DetailBase):
    """命令 durable commit 后的 ACK。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["command_ack"] = "command_ack"
    command_id: UUID
    operation_id: UUID
    state: Literal["received", "executing", "completed", "failed", "unknown"]
    replayed: bool
    recovery_required: bool


class AgentCommandResultReference(BaseModel):
    """不含正文的 App Server 结果定位摘要。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    upstream_thread_id: str | None = Field(default=None, max_length=256)
    upstream_turn_id: str | None = Field(default=None, max_length=256)
    status: str | None = Field(default=None, max_length=64)


class AgentThreadReadCommandResult(BaseModel):
    """thread/read 命令的完整强类型结果正文。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["thread.read"] = "thread.read"
    snapshot: AppServerThreadReadProductResult


AgentCommandResultPayload = Annotated[
    AgentThreadReadCommandResult,
    Field(discriminator="kind"),
]


class AgentCommandResultV2Detail(AgentProtocolV2DetailBase):
    """命令最终结果；未知结果禁止自动重放 mutation。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["command_result"] = "command_result"
    command_id: UUID
    operation_id: UUID
    outcome: Literal["completed", "failed", "unknown"]
    result: AgentCommandResultPayload | None = None
    reference: AgentCommandResultReference | None = None
    error_code: str | None = Field(default=None, max_length=128)
    error_summary: str | None = Field(default=None, max_length=512)


class AgentThreadSnapshot(AgentProtocolV2DetailBase):
    """Agent snapshot 中稳定线程索引字段。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["conversation_snapshot"] = "conversation_snapshot"
    thread_id: str = Field(min_length=1, max_length=256)
    workspace_key: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=256)
    title_source: CodexThreadTitleSource
    status: str = Field(min_length=1, max_length=64)
    active_turn_id: str | None = Field(default=None, max_length=256)
    archived: bool
    model_id: str | None = Field(default=None, max_length=128)
    model_provider: str | None = Field(default=None, max_length=128)
    created_at: datetime
    recency_at: datetime


class AgentWorkspaceSnapshot(AgentProtocolV2DetailBase):
    """Agent snapshot 中脱敏工作区字段。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["workspace_snapshot"] = "workspace_snapshot"
    workspace_key: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=128)
    repo_fingerprint: str | None = Field(default=None, pattern=SHA256_HEX_PATTERN)
    default_branch: str | None = Field(default=None, max_length=256)
    allow_write: bool
    execution_preferences: CodexWorkspaceExecutionPreferences | None = None


class AgentPendingCommandSnapshot(AgentProtocolV2DetailBase):
    """本地 journal 有界恢复摘要，包括最近终态。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["pending_command_snapshot"] = "pending_command_snapshot"
    command_id: UUID
    operation_id: UUID
    command_kind: str = Field(min_length=1, max_length=64)
    state: Literal["received", "executing", "completed", "failed", "unknown"]
    recovery_required: bool
    result_summary: AgentCommandResultSummary | None = None


class AgentPendingApprovalSnapshot(AgentProtocolV2DetailBase):
    """仍可回复的审批代次摘要。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["pending_approval_snapshot"] = "pending_approval_snapshot"
    approval_id: UUID
    app_server_instance_id: UUID
    approval_kind: Literal["command", "file_change", "permissions"]
    thread_id: str = Field(min_length=1, max_length=256)
    turn_id: str = Field(min_length=1, max_length=256)
    item_id: str = Field(min_length=1, max_length=256)
    payload_digest: str = Field(pattern=SHA256_HEX_PATTERN)
    version: int = Field(ge=1)
    expires_at: datetime
    display: AgentApprovalDisplaySummary


class AgentSnapshotOmission(AgentProtocolV2DetailBase):
    """快照容量超限时的显式省略信息。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["snapshot_omission"] = "snapshot_omission"
    section: Literal["threads", "pending_commands", "pending_approvals"]
    omitted_count: int = Field(gt=0)
    reason: Literal["frame_capacity", "page_capacity"]


class AgentStateSnapshotV2Detail(AgentProtocolV2DetailBase):
    """可分页且受 frame 上限约束的权威快照。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["state_snapshot"] = "state_snapshot"
    execution_generation: int | None = Field(default=None, ge=0)
    app_server_instance_id: UUID
    page_index: int = Field(ge=0)
    continuation_token: str | None = Field(default=None, max_length=512)
    workspaces: tuple[AgentWorkspaceSnapshot, ...]
    threads: tuple[AgentThreadSnapshot, ...]
    pending_commands: tuple[AgentPendingCommandSnapshot, ...]
    pending_approvals: tuple[AgentPendingApprovalSnapshot, ...]
    omissions: tuple[AgentSnapshotOmission, ...] = ()
    captured_at: datetime


class AgentEventType(StrEnum):
    """Agent 到控制面的稳定产品事件类型。"""

    THREAD_CHANGED = "thread.changed"
    THREAD_METADATA_CHANGED = "thread.metadata_changed"
    TURN_CHANGED = "turn.changed"
    ITEM_CHANGED = "item.changed"
    ITEM_DELTA = "item.delta"
    PLAN_CHANGED = "plan.changed"
    DIFF_CHANGED = "diff.changed"
    APPROVAL_OPENED = "approval.opened"
    PROTOCOL_WARNING = "protocol.warning"
    GAP = "gap"


class AgentThreadChangedEventDetail(AgentProtocolV2DetailBase):
    """线程状态变更。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["thread.changed"] = "thread.changed"
    method: Literal[
        AppServerNotificationName.THREAD_STARTED,
        AppServerNotificationName.THREAD_STATUS_CHANGED,
    ]
    thread: AppServerThreadProductSnapshot


class AgentThreadMetadataChangedEventDetail(AgentProtocolV2DetailBase):
    """线程名称或归档状态变更。"""

    kind: Literal["thread.metadata_changed"] = "thread.metadata_changed"
    method: Literal[
        AppServerNotificationName.THREAD_NAME_UPDATED,
        AppServerNotificationName.THREAD_ARCHIVED,
        AppServerNotificationName.THREAD_UNARCHIVED,
        AppServerNotificationName.THREAD_SETTINGS_UPDATED,
    ]
    thread_id: str = Field(min_length=1, max_length=256)
    display_name: str | None = Field(default=None, max_length=256)
    archived: bool | None = None
    execution_settings: CodexEffectiveExecutionSettings | None = None


class AgentTurnChangedEventDetail(AgentProtocolV2DetailBase):
    """turn 状态变更。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["turn.changed"] = "turn.changed"
    method: Literal[
        AppServerNotificationName.TURN_STARTED,
        AppServerNotificationName.TURN_COMPLETED,
    ]
    thread_id: str = Field(min_length=1, max_length=256)
    turn_id: str = Field(min_length=1, max_length=256)
    status: str = Field(min_length=1, max_length=64)


class AgentItemDeltaEventDetail(AgentProtocolV2DetailBase):
    """允许批处理的文本 delta。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["item.delta"] = "item.delta"
    method: Literal[
        AppServerNotificationName.AGENT_MESSAGE_DELTA,
        AppServerNotificationName.COMMAND_OUTPUT_DELTA,
        AppServerNotificationName.FILE_OUTPUT_DELTA,
    ]
    thread_id: str = Field(min_length=1, max_length=256)
    turn_id: str = Field(min_length=1, max_length=256)
    item_id: str = Field(min_length=1, max_length=256)
    delta: str = Field(max_length=APP_SERVER_PRODUCT_MAX_DELTA_CHARS)


class AgentItemChangedEventDetail(AgentProtocolV2DetailBase):
    """item 创建或完成的稳定索引。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["item.changed"] = "item.changed"
    method: Literal[
        AppServerNotificationName.ITEM_STARTED,
        AppServerNotificationName.ITEM_COMPLETED,
        AppServerNotificationName.FILE_PATCH_UPDATED,
    ]
    thread_id: str = Field(min_length=1, max_length=256)
    turn_id: str | None = Field(default=None, max_length=256)
    status: Literal["started", "completed"]
    item: AppServerProductTimelineItem


class AgentPlanChangedEventDetail(AgentProtocolV2DetailBase):
    """计划步骤结构化变更。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["plan.changed"] = "plan.changed"
    thread_id: str = Field(min_length=1, max_length=256)
    turn_id: str = Field(min_length=1, max_length=256)
    explanation: str | None = Field(default=None, max_length=APP_SERVER_PRODUCT_MAX_TEXT_CHARS)
    steps: tuple[AppServerPlanStep, ...]


class AgentDiffChangedEventDetail(AgentProtocolV2DetailBase):
    """diff 完成或截断状态，不在该摘要中重复正文。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["diff.changed"] = "diff.changed"
    thread_id: str = Field(min_length=1, max_length=256)
    turn_id: str = Field(min_length=1, max_length=256)
    unified_diff: str = Field(max_length=APP_SERVER_PRODUCT_MAX_TEXT_CHARS)
    truncated: bool


class AgentApprovalOpenedEventDetail(AgentProtocolV2DetailBase):
    """审批打开事件。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["approval.opened"] = "approval.opened"
    approval: AgentPendingApprovalSnapshot


class AgentProtocolWarningEventDetail(AgentProtocolV2DetailBase):
    """不携带未知原始 payload 的协议告警。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["protocol.warning"] = "protocol.warning"
    reason_code: str = Field(min_length=1, max_length=128)
    method: str | None = Field(default=None, max_length=128)
    count: int = Field(default=1, ge=1)


class AgentApprovalResolvedEventDetail(AgentProtocolV2DetailBase):
    """The native request was cleared; this never asserts tool success."""

    kind: Literal["approval.resolved"] = "approval.resolved"
    approval_id: UUID
    thread_id: str = Field(min_length=1, max_length=256)
    turn_id: str = Field(min_length=1, max_length=256)
    reason: Literal["resolved", "expired", "turn_ended", "instance_replaced"]


class AgentGapEventDetail(AgentProtocolV2DetailBase):
    """replay buffer trim 后的 gap。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["gap"] = "gap"
    first_available_seq: int = Field(ge=1)
    snapshot_required: Literal[True] = True


AgentEventDetail = Annotated[
    AgentThreadChangedEventDetail
    | AgentThreadMetadataChangedEventDetail
    | AgentTurnChangedEventDetail
    | AgentItemChangedEventDetail
    | AgentItemDeltaEventDetail
    | AgentPlanChangedEventDetail
    | AgentDiffChangedEventDetail
    | AgentApprovalOpenedEventDetail
    | AgentApprovalResolvedEventDetail
    | AgentProtocolWarningEventDetail
    | AgentGapEventDetail,
    Field(discriminator="kind"),
]


class AgentEventRecord(BaseModel):
    """由 `(agent_event_epoch, seq)` 唯一定位的事件。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    agent_event_epoch: UUID
    seq: int = Field(ge=1)
    event_id: UUID
    app_server_instance_id: UUID
    occurred_at: datetime
    detail: AgentEventDetail


class AgentEventBatchV2Detail(AgentProtocolV2DetailBase):
    """连续事件批次。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["event_batch"] = "event_batch"
    agent_event_epoch: UUID
    first_seq: int = Field(ge=1)
    last_seq: int = Field(ge=1)
    events: tuple[AgentEventRecord, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_contiguous_sequence(self) -> AgentEventBatchV2Detail:
        """批次必须连续且边界与事件一致。"""

        sequences = [event.seq for event in self.events]
        expected = list(range(self.first_seq, self.last_seq + 1))
        if sequences != expected:
            raise ValueError("Agent事件批次seq必须严格连续。")
        if any(event.agent_event_epoch != self.agent_event_epoch for event in self.events):
            raise ValueError("Agent事件批次epoch必须一致。")
        return self


class AgentEventAckV2Detail(AgentProtocolV2DetailBase):
    """控制面对 Agent 事件的累计 ACK。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["event_ack"] = "event_ack"
    agent_event_epoch: UUID
    after_seq: int = Field(ge=0)


class AgentReplayRequestV2Detail(AgentProtocolV2DetailBase):
    """控制面请求从累计 ACK 后重放。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["replay_request"] = "replay_request"
    agent_event_epoch: UUID
    after_seq: int = Field(ge=0)


AgentProtocolV2Detail = Annotated[
    AgentHelloV2Detail
    | AgentHelloAckV2Detail
    | AgentHeartbeatV2Detail
    | AgentExecutionLeaseV2Detail
    | AgentExecutionStoppedV2Detail
    | AgentCommandV2Detail
    | AgentCommandAckV2Detail
    | AgentCommandResultV2Detail
    | AgentEventBatchV2Detail
    | AgentEventAckV2Detail
    | AgentReplayRequestV2Detail
    | AgentStateSnapshotV2Detail,
    Field(discriminator="kind"),
]


class AgentProtocolV2Envelope(BaseModel):
    """Agent protocol v2 公共头与强类型扩展字段信封。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    header: AgentProtocolV2Header
    detail: AgentProtocolV2Detail

    @model_validator(mode="after")
    def validate_message_type(self) -> AgentProtocolV2Envelope:
        """公共头消息类型必须与 detail discriminator 一致。"""

        if self.header.message_type.value != self.detail.kind:
            raise ValueError("Agent protocol v2消息头与detail类型不一致。")
        if self.header.detail_kind != self.header.message_type:
            raise ValueError("Agent protocol v2消息头类型字段不一致。")
        if self.header.schema_version != self.detail.schema_version:
            raise ValueError("Agent protocol v2消息头与detail版本不一致。")
        return self
