"""Agent 事件有界重放缓冲。"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from src.core.codex_contract.agent_protocol_v2_contract import AgentEventRecord
from src.core.codex_contract.connection_session_contract import CodexConnectionFrame

AGENT_REPLAY_BUFFER_DEFAULT_CAPACITY: Final[int] = 2_000


@dataclass(frozen=True, slots=True)
class AgentBufferedEvent:
    """同时承载 v1 迁移帧与 v2 typed event 的统一缓冲项。"""

    epoch: UUID
    seq: int
    frame: CodexConnectionFrame
    record: AgentEventRecord | None = None


@dataclass(frozen=True, slots=True)
class AgentReplayWindow:
    """重放结果及是否需要权威 snapshot。"""

    events: tuple[AgentBufferedEvent, ...]
    snapshot_required: bool
    first_available_seq: int | None


class AgentEventReplayBuffer:
    """有界、单写者事件窗口；trim 不泄露内部 deque。"""

    def __init__(self, *, capacity: int, max_bytes: int = 16 * 1024 * 1024) -> None:
        if capacity <= 0:
            raise ValueError("Agent事件重放缓冲容量必须大于零。")
        self._events: deque[AgentBufferedEvent] = deque()
        self._capacity = capacity
        self._max_bytes = max_bytes
        self._sizes: deque[int] = deque()
        self._trimmed = False
        self._total_bytes = 0

    @property
    def size(self) -> int:
        """返回当前窗口大小。"""

        return len(self._events)

    def append(self, event: AgentBufferedEvent) -> None:
        """追加事件并在超限时记录 gap。"""

        size = len(event.frame.model_dump_json().encode("utf-8"))
        if event.record is not None:
            size += len(event.record.model_dump_json().encode("utf-8"))
        while self._events and (
            len(self._events) >= self._capacity or self._total_bytes + size > self._max_bytes
        ):
            self._events.popleft()
            self._total_bytes -= self._sizes.popleft()
            self._trimmed = True
        if size > self._max_bytes:
            self._trimmed = True
            return
        self._events.append(event)
        self._sizes.append(size)
        self._total_bytes += size

    def read_after(self, *, epoch: UUID, after_seq: int) -> AgentReplayWindow:
        """按 epoch 与累计 ACK 返回可重放窗口。"""

        events = tuple(
            item for item in self._events if item.epoch == epoch and item.seq > after_seq
        )
        first = self._events[0].seq if self._events and self._events[0].epoch == epoch else None
        snapshot_required = self._trimmed and (first is None or after_seq < first - 1)
        return AgentReplayWindow(
            events=events,
            snapshot_required=snapshot_required,
            first_available_seq=first,
        )

    def discard_acknowledged(self, *, epoch: UUID, after_seq: int) -> None:
        """删除已被服务端累计确认的事件。"""

        retained = tuple(
            item for item in self._events if item.epoch != epoch or item.seq > after_seq
        )
        trimmed = self._trimmed
        self.clear()
        for item in retained:
            self.append(item)
        self._trimmed = trimmed

    def clear(self) -> None:
        """清空本地缓冲并重置 gap 标志。"""

        self._events.clear()
        self._sizes.clear()
        self._total_bytes = 0
        self._trimmed = False
