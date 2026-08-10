"""浏览器使用的 Codex 稳定产品实时事件契约。"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue

CODEX_REALTIME_SCHEMA_VERSION: Literal["2.0"] = "2.0"
CODEX_REALTIME_OPERATION_NAME = "codex.events"
CODEX_REALTIME_STREAM_EPOCH = "codex-browser-stream-v2"


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


class CodexRealtimeEvent(BaseModel):
    """隔离 App Server JSON-RPC 的浏览器产品事件。"""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["codex_realtime_event"] = "codex_realtime_event"
    schema_version: Literal["2.0"] = CODEX_REALTIME_SCHEMA_VERSION
    stream_epoch: str = Field(default=CODEX_REALTIME_STREAM_EPOCH, min_length=1, max_length=128)
    cursor: str | None = Field(default=None, max_length=512)
    event_id: str = Field(min_length=1, max_length=128)
    host_id: UUID
    workspace_id: UUID | None = None
    thread_id: str | None = Field(default=None, max_length=256)
    turn_id: str | None = Field(default=None, max_length=256)
    item_id: str | None = Field(default=None, max_length=256)
    type: CodexRealtimeEventType
    payload: dict[str, JsonValue] = Field(default_factory=dict)


class CodexRealtimeTicket(BaseModel):
    """只在签发响应中出现一次的浏览器 WebSocket 票据。"""

    model_config = ConfigDict(extra="forbid")

    ticket: str = Field(min_length=32, max_length=512)
    expires_at: datetime


class CodexRealtimeTicketSubject(BaseModel):
    """编码进通用 ticket subject 的浏览器 owner 与 cursor 权限。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    owner_subject_id: str = Field(min_length=1, max_length=128)
    audience: Literal["codex.events"] = "codex.events"
    cursor_read_allowed: Literal[True] = True

    def encode(self) -> str:
        return self.model_dump_json()

    @classmethod
    def decode(cls, value: str) -> CodexRealtimeTicketSubject:
        return cls.model_validate_json(value)
