"""浏览器使用的 Codex 稳定产品实时事件契约。"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Final, Literal, Self, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from src.core.codex_contract.approval_contract import CodexApprovalAuditSnapshot
from src.core.codex_contract.host_contract import CodexHostSnapshot
from src.core.codex_contract.thread_contract import (
    CodexDiffSnapshot,
    CodexPlanStepSnapshot,
    CodexThreadHistoryStatus,
    CodexThreadIndexSnapshot,
    CodexThreadStatus,
    CodexTimelineItemEnvelope,
    CodexTurnSnapshot,
)
from src.core.codex_contract.turn_runtime_contract import CodexTurnRuntime
from src.core.codex_contract.workspace_contract import CodexWorkspaceSnapshot

CODEX_REALTIME_SCHEMA_VERSION: Final = "2.0"
CODEX_REALTIME_OPERATION_NAME: Final = "codex.events"
CODEX_REALTIME_STREAM_EPOCH: Final = "codex-browser-stream-v2"
CODEX_REALTIME_WARNING_MAX_LENGTH: Final = 512
CODEX_REALTIME_DELTA_MAX_LENGTH: Final = 65_536


class CodexRealtimeEventType(StrEnum):
    """Nuxt reducer 可长期依赖的产品事件类型。"""

    CONNECTION_READY = "connection.ready"
    CONNECTION_HEARTBEAT = "connection.heartbeat"
    HOST_SNAPSHOT = "host.snapshot"
    HOST_STATUS_CHANGED = "host.status_changed"
    WORKSPACE_SNAPSHOT = "workspace.snapshot"
    THREAD_SNAPSHOT = "thread.snapshot"
    THREAD_UPDATED = "thread.updated"
    TURN_STARTED = "turn.started"
    TURN_COMPLETED = "turn.completed"
    TURN_FAILED = "turn.failed"
    TURN_INTERRUPTED = "turn.interrupted"
    TURN_PLAN_UPDATED = "turn.plan_updated"
    TURN_DIFF_UPDATED = "turn.diff_updated"
    ITEM_UPSERT = "item.upsert"
    ITEM_DELTA = "item.delta"
    APPROVAL_OPENED = "approval.opened"
    APPROVAL_RESOLVED = "approval.resolved"
    STREAM_GAP_DETECTED = "stream.gap_detected"
    PROTOCOL_WARNING = "protocol.warning"


class CodexRealtimeEventHeader(BaseModel):
    """浏览器实时事件共享的游标与实体定位头。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["codex_realtime_event"] = "codex_realtime_event"
    schema_version: Literal["2.0"] = CODEX_REALTIME_SCHEMA_VERSION
    stream_epoch: str = Field(default=CODEX_REALTIME_STREAM_EPOCH, min_length=1, max_length=128)
    cursor: str | None = Field(default=None, max_length=512)
    event_id: str = Field(min_length=1, max_length=128)
    source_epoch: UUID | None = None
    source_seq: int | None = Field(default=None, ge=0)
    occurred_at: datetime
    host_id: UUID
    workspace_id: UUID | None = None
    thread_id: str | None = Field(default=None, max_length=256)
    turn_id: str | None = Field(default=None, max_length=256)
    item_id: str | None = Field(default=None, max_length=256)
    detail_kind: CodexRealtimeEventType


class CodexRealtimeDetailBase(BaseModel):
    """浏览器实时事件强类型扩展字段基类。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["2.0"] = CODEX_REALTIME_SCHEMA_VERSION


class CodexConnectionReadyDetail(CodexRealtimeDetailBase):
    """连接建立后的心跳配置。"""

    kind: Literal["connection.ready"] = "connection.ready"
    heartbeat_interval: int = Field(gt=0)
    server_time: datetime


class CodexConnectionHeartbeatDetail(CodexRealtimeDetailBase):
    """浏览器连接心跳。"""

    kind: Literal["connection.heartbeat"] = "connection.heartbeat"
    server_time: datetime


class CodexHostSnapshotDetail(CodexRealtimeDetailBase):
    """当前主体可见主机快照。"""

    kind: Literal["host.snapshot"] = "host.snapshot"
    hosts: tuple[CodexHostSnapshot, ...]


class CodexHostStatusChangedDetail(CodexRealtimeDetailBase):
    """主机在线状态变化。"""

    kind: Literal["host.status_changed"] = "host.status_changed"
    host_id: UUID
    status: str = Field(min_length=1, max_length=32)
    last_seen_at: datetime | None = None


class CodexWorkspaceSnapshotDetail(CodexRealtimeDetailBase):
    """当前主体可见项目快照。"""

    kind: Literal["workspace.snapshot"] = "workspace.snapshot"
    workspaces: tuple[CodexWorkspaceSnapshot, ...]


class CodexThreadSnapshotDetail(CodexRealtimeDetailBase):
    """会话索引与可选历史正文快照。"""

    kind: Literal["thread.snapshot"] = "thread.snapshot"
    source_epoch: UUID | None = None
    source_seq: int = Field(default=0, ge=0)
    covered_item_ids: list[str] = Field(default_factory=list, max_length=200)
    thread: CodexThreadIndexSnapshot
    turns: tuple[CodexTurnSnapshot, ...]
    items: tuple[CodexTimelineItemEnvelope, ...]
    history_status: CodexThreadHistoryStatus
    history_before_cursor: str | None = Field(default=None, max_length=2_048)
    history_has_more: bool = False
    history_revision: str | None = Field(default=None, min_length=64, max_length=64)


class CodexThreadPatch(BaseModel):
    """实时事件允许更新的会话索引字段。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    host_id: UUID
    workspace_id: UUID
    upstream_thread_id: str = Field(min_length=1, max_length=256)
    display_name: str | None = Field(default=None, min_length=1, max_length=256)
    title_source: str | None = Field(default=None, max_length=32)
    model: str | None = Field(default=None, max_length=128)
    model_provider: str | None = Field(default=None, max_length=128)
    reasoning_effort: str | None = Field(default=None, max_length=64)
    status: CodexThreadStatus | None = None
    active_turn_id: str | None = Field(default=None, max_length=256)
    turn_runtime: CodexTurnRuntime | None = None
    archived: bool | None = None
    is_pinned: bool | None = None
    created_at: datetime | None = None
    recency_at: datetime | None = None
    updated_at: datetime | None = None


class CodexThreadUpdatedDetail(CodexRealtimeDetailBase):
    """会话索引增量更新。"""

    kind: Literal["thread.updated"] = "thread.updated"
    thread: CodexThreadPatch


class CodexTurnChangedDetail(CodexRealtimeDetailBase):
    """turn 启动、完成、失败或中断。"""

    kind: Literal[
        "turn.started",
        "turn.completed",
        "turn.failed",
        "turn.interrupted",
    ]
    turn: CodexTurnSnapshot


class CodexPlanUpdatedDetail(CodexRealtimeDetailBase):
    """结构化计划更新。"""

    kind: Literal["turn.plan_updated"] = "turn.plan_updated"
    item_id: str = Field(min_length=1, max_length=256)
    thread_id: str = Field(min_length=1, max_length=256)
    turn_id: str | None = Field(default=None, max_length=256)
    explanation: str = Field(default="", max_length=1_048_576)
    steps: tuple[CodexPlanStepSnapshot, ...]


class CodexDiffUpdatedDetail(CodexRealtimeDetailBase):
    """结构化 Diff 更新。"""

    kind: Literal["turn.diff_updated"] = "turn.diff_updated"
    item_id: str = Field(min_length=1, max_length=256)
    thread_id: str = Field(min_length=1, max_length=256)
    turn_id: str | None = Field(default=None, max_length=256)
    diff: CodexDiffSnapshot


class CodexItemUpsertDetail(CodexRealtimeDetailBase):
    """完整时间线条目更新。"""

    kind: Literal["item.upsert"] = "item.upsert"
    item: CodexTimelineItemEnvelope


class CodexItemDeltaDetail(CodexRealtimeDetailBase):
    """有界时间线文本增量。"""

    kind: Literal["item.delta"] = "item.delta"
    item_id: str = Field(min_length=1, max_length=256)
    thread_id: str = Field(min_length=1, max_length=256)
    turn_id: str | None = Field(default=None, max_length=256)
    delta: str = Field(max_length=CODEX_REALTIME_DELTA_MAX_LENGTH)


class CodexApprovalEventDetail(CodexRealtimeDetailBase):
    """审批打开或解决事件。"""

    kind: Literal["approval.opened", "approval.resolved"]
    approval: CodexApprovalAuditSnapshot


class CodexStreamGapDetail(CodexRealtimeDetailBase):
    """实时流缺口与权威回源要求。"""

    kind: Literal["stream.gap_detected"] = "stream.gap_detected"
    reason: str = Field(min_length=1, max_length=128)
    snapshot_required: bool = True
    server_time: datetime | None = None


class CodexProtocolWarningDetail(CodexRealtimeDetailBase):
    """不携带未知原始正文的协议告警。"""

    kind: Literal["protocol.warning"] = "protocol.warning"
    warning: str = Field(min_length=1, max_length=CODEX_REALTIME_WARNING_MAX_LENGTH)


CodexRealtimeEventDetail = Annotated[
    CodexConnectionReadyDetail
    | CodexConnectionHeartbeatDetail
    | CodexHostSnapshotDetail
    | CodexHostStatusChangedDetail
    | CodexWorkspaceSnapshotDetail
    | CodexThreadSnapshotDetail
    | CodexThreadUpdatedDetail
    | CodexTurnChangedDetail
    | CodexPlanUpdatedDetail
    | CodexDiffUpdatedDetail
    | CodexItemUpsertDetail
    | CodexItemDeltaDetail
    | CodexApprovalEventDetail
    | CodexStreamGapDetail
    | CodexProtocolWarningDetail,
    Field(discriminator="kind"),
]


class CodexRealtimeEvent(BaseModel):
    """浏览器实时事件公共头与强类型扩展字段信封。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    header: CodexRealtimeEventHeader
    detail: CodexRealtimeEventDetail

    @model_validator(mode="after")
    def validate_detail_identity(self) -> Self:
        """拒绝头部与扩展字段类型或版本不一致的事件。"""

        if self.header.detail_kind.value != self.detail.kind:
            raise ValueError("实时事件头与扩展类型不一致。")
        if self.header.schema_version != self.detail.schema_version:
            raise ValueError("实时事件头与扩展版本不一致。")
        return self


class CodexRealtimeDetailFactory:
    """把内部受控映射收窄为封闭实时事件扩展。"""

    _DETAIL_MODELS: Final = {
        CodexRealtimeEventType.CONNECTION_READY: CodexConnectionReadyDetail,
        CodexRealtimeEventType.CONNECTION_HEARTBEAT: CodexConnectionHeartbeatDetail,
        CodexRealtimeEventType.HOST_SNAPSHOT: CodexHostSnapshotDetail,
        CodexRealtimeEventType.HOST_STATUS_CHANGED: CodexHostStatusChangedDetail,
        CodexRealtimeEventType.WORKSPACE_SNAPSHOT: CodexWorkspaceSnapshotDetail,
        CodexRealtimeEventType.THREAD_SNAPSHOT: CodexThreadSnapshotDetail,
        CodexRealtimeEventType.THREAD_UPDATED: CodexThreadUpdatedDetail,
        CodexRealtimeEventType.TURN_STARTED: CodexTurnChangedDetail,
        CodexRealtimeEventType.TURN_COMPLETED: CodexTurnChangedDetail,
        CodexRealtimeEventType.TURN_FAILED: CodexTurnChangedDetail,
        CodexRealtimeEventType.TURN_INTERRUPTED: CodexTurnChangedDetail,
        CodexRealtimeEventType.TURN_PLAN_UPDATED: CodexPlanUpdatedDetail,
        CodexRealtimeEventType.TURN_DIFF_UPDATED: CodexDiffUpdatedDetail,
        CodexRealtimeEventType.ITEM_UPSERT: CodexItemUpsertDetail,
        CodexRealtimeEventType.ITEM_DELTA: CodexItemDeltaDetail,
        CodexRealtimeEventType.APPROVAL_OPENED: CodexApprovalEventDetail,
        CodexRealtimeEventType.APPROVAL_RESOLVED: CodexApprovalEventDetail,
        CodexRealtimeEventType.STREAM_GAP_DETECTED: CodexStreamGapDetail,
        CodexRealtimeEventType.PROTOCOL_WARNING: CodexProtocolWarningDetail,
    }

    def build(
        self,
        event_type: CodexRealtimeEventType,
        payload: BaseModel | Mapping[str, object],
    ) -> CodexRealtimeEventDetail:
        """按事件种类校验并构造对应强类型扩展。"""

        if event_type not in self._DETAIL_MODELS:
            raise ValueError("实时事件类型未注册。")
        source = payload.model_dump(mode="python") if isinstance(payload, BaseModel) else payload
        validated: object = TypeAdapter(CodexRealtimeEventDetail).validate_python(
            {"kind": event_type.value, **source}
        )
        return cast(CodexRealtimeEventDetail, validated)


class CodexRealtimeTicket(BaseModel):
    """只在签发响应中出现一次的浏览器 WebSocket 票据。"""

    model_config = ConfigDict(extra="forbid")

    ticket: str = Field(min_length=32, max_length=512)
    expires_at: datetime


class CodexRealtimeTicketSubject(BaseModel):
    """编码进通用 ticket subject 的浏览器 owner 与 cursor 权限。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    owner_subject_id: str = Field(min_length=1, max_length=128)
    audience: Literal["codex.events"] = CODEX_REALTIME_OPERATION_NAME
    cursor_read_allowed: Literal[True] = True

    def encode(self) -> str:
        """编码一次性票据主体。"""

        return self.model_dump_json()

    @classmethod
    def decode(cls, value: str) -> CodexRealtimeTicketSubject:
        """解码并校验一次性票据主体。"""

        return cls.model_validate_json(value)
