"""Codex 浏览器实时批次与权威快照契约。

批次只负责传输有序事件，不改变单事件的业务语义。快照携带事件流边界，
使浏览器可以在恢复期间缓冲事件并在快照游标之后安全重放。
"""

from __future__ import annotations

from typing import Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.core.codex_contract.approval_contract import CodexApprovalAuditSnapshot
from src.core.codex_contract.realtime_event_contract import (
    CodexRealtimeEvent,
    CodexRealtimeEventType,
)
from src.core.codex_contract.thread_contract import (
    CodexThreadIndexSnapshot,
    CodexTimelineItemEnvelope,
)
from src.core.codex_contract.turn_runtime_contract import CodexTurnRuntime

CODEX_REALTIME_BATCH_PROTOCOL_VERSION: Final[Literal[2]] = 2
CODEX_REALTIME_BATCH_MAX_EVENTS: Final[int] = 64
CODEX_REALTIME_BATCH_MAX_BYTES: Final[int] = 65_536
CODEX_REALTIME_BATCH_BARRIER_EVENT_TYPES: Final[frozenset[CodexRealtimeEventType]] = frozenset(
    {
        CodexRealtimeEventType.TURN_COMPLETED,
        CodexRealtimeEventType.TURN_FAILED,
        CodexRealtimeEventType.TURN_INTERRUPTED,
        CodexRealtimeEventType.APPROVAL_OPENED,
        CodexRealtimeEventType.APPROVAL_RESOLVED,
        CodexRealtimeEventType.STREAM_GAP_DETECTED,
        CodexRealtimeEventType.PROTOCOL_WARNING,
    }
)


def is_codex_realtime_batch_barrier(event_type: CodexRealtimeEventType) -> bool:
    """返回必须独占浏览器传输边界的终态、审批和恢复事件。"""

    return event_type in CODEX_REALTIME_BATCH_BARRIER_EVENT_TYPES


class CodexRealtimeBatch(BaseModel):
    """浏览器一次提交的有序实时事件批次。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    protocol_version: Literal[2] = CODEX_REALTIME_BATCH_PROTOCOL_VERSION
    stream_epoch: str = Field(min_length=1, max_length=128)
    first_cursor: str | None = Field(default=None, max_length=512)
    last_cursor: str | None = Field(default=None, max_length=512)
    barrier: bool = False
    events: tuple[CodexRealtimeEvent, ...] = Field(
        min_length=1, max_length=CODEX_REALTIME_BATCH_MAX_EVENTS
    )

    @model_validator(mode="after")
    def validate_boundaries(self) -> Self:
        """保证批次边界与事件流 epoch、首尾游标保持一致。"""

        if any(event.header.stream_epoch != self.stream_epoch for event in self.events):
            raise ValueError("实时批次包含跨stream_epoch事件。")
        cursors = tuple(event.header.cursor for event in self.events)
        if (self.first_cursor, self.last_cursor) != (cursors[0], cursors[-1]):
            raise ValueError("实时批次首尾游标与事件不一致。")
        if any(cursor is None for cursor in cursors) and any(
            cursor is not None for cursor in cursors
        ):
            raise ValueError("实时批次不允许混合有游标和无游标事件。")
        if self.barrier and any(
            not is_codex_realtime_batch_barrier(event.header.detail_kind) for event in self.events
        ):
            raise ValueError("实时屏障批次只能包含终态、审批、错误或恢复事件。")
        return self


class CodexAuthoritySnapshot(BaseModel):
    """浏览器恢复使用的权威投影快照。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    stream_epoch: str = Field(min_length=1, max_length=128)
    snapshot_cursor: str = Field(min_length=1, max_length=512)
    projection_revision: str = Field(min_length=1, max_length=128)
    thread: CodexThreadIndexSnapshot
    timeline_items: tuple[CodexTimelineItemEnvelope, ...]
    turns: tuple[CodexTurnRuntime, ...]
    approvals: tuple[CodexApprovalAuditSnapshot, ...]
