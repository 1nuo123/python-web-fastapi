"""Agent 高频事件的有界批处理器。"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Final

from src.core.codex_contract.agent_protocol_v2_contract import (
    AgentEventBatchV2Detail,
    AgentEventRecord,
    AgentEventType,
)

AGENT_EVENT_BATCH_WINDOW: Final[timedelta] = timedelta(milliseconds=25)
AGENT_EVENT_BATCH_MAX_BYTES: Final[int] = 16 * 1024
DELTA_EVENT_TYPES: Final[frozenset[AgentEventType]] = frozenset({AgentEventType.ITEM_DELTA})


@dataclass(frozen=True, slots=True)
class AgentEventBatcherResult:
    """一次输入导致的批次输出。"""

    flushed: tuple[AgentEventBatchV2Detail, ...]


class AgentEventBatcher:
    """只合并连续 delta；完成、审批、错误等事件形成 ordering barrier。"""

    def __init__(
        self,
        *,
        window: timedelta = AGENT_EVENT_BATCH_WINDOW,
        max_bytes: int = AGENT_EVENT_BATCH_MAX_BYTES,
        encoded_size: Callable[[AgentEventBatchV2Detail], int] | None = None,
    ) -> None:
        if window.total_seconds() <= 0:
            raise ValueError("Agent事件批处理窗口必须大于零。")
        if max_bytes <= 0:
            raise ValueError("Agent事件批处理字节上限必须大于零。")
        self._window = window
        self._max_bytes = max_bytes
        self._encoded_size = encoded_size or (
            lambda batch: len(batch.model_dump_json().encode("utf-8"))
        )
        self._pending: list[AgentEventRecord] = []
        self._started_at: datetime | None = None
        self._byte_count = 0

    @property
    def has_pending(self) -> bool:
        """返回是否存在尚未输出的 delta。"""

        return bool(self._pending)

    def push(
        self, event: AgentEventRecord, *, now: datetime | None = None
    ) -> AgentEventBatcherResult:
        """写入一个事件并按时间、UTF-8 字节数或 barrier 规则输出。"""

        current_time = now or datetime.now(UTC)
        flushed: list[AgentEventBatchV2Detail] = []
        is_delta = event.detail.kind in {item.value for item in DELTA_EVENT_TYPES}
        if self._pending and (
            not is_delta
            or event.agent_event_epoch != self._pending[-1].agent_event_epoch
            or self._started_at is None
            or current_time - self._started_at >= self._window
            or self._encoded_size(self._build_batch((*self._pending, event))) > self._max_bytes
        ):
            flushed.append(self.flush())
        if is_delta:
            if not self._pending:
                self._started_at = current_time
            self._pending.append(event)
            self._byte_count = self._encoded_size(self._build_batch(tuple(self._pending)))
            if self._byte_count >= self._max_bytes:
                flushed.append(self.flush())
        else:
            flushed.append(self._build_batch((event,)))
        return AgentEventBatcherResult(flushed=tuple(flushed))

    def flush(self) -> AgentEventBatchV2Detail:
        """立即输出当前 delta 队列；无待处理事件时报错。"""

        if not self._pending:
            raise ValueError("Agent事件批处理器没有待输出事件。")
        batch = self._build_batch(tuple(self._pending))
        self._pending.clear()
        self._started_at = None
        self._byte_count = 0
        return batch

    def _build_batch(self, events: tuple[AgentEventRecord, ...]) -> AgentEventBatchV2Detail:
        return AgentEventBatchV2Detail(
            agent_event_epoch=events[0].agent_event_epoch,
            first_seq=events[0].seq,
            last_seq=events[-1].seq,
            events=events,
        )
