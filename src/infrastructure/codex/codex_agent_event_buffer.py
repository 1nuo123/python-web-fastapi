"""FastAPI 控制面接收 Agent 实时事件的有界缓冲。"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from src.core.codex_contract.agent_device_auth_contract import AgentDevicePrincipal
from src.core.codex_contract.agent_protocol_contract import CodexAgentRealtimeEvent


@dataclass(frozen=True, slots=True)
class BufferedCodexAgentEvent:
    """控制面接收的 host 内递增事件。"""

    sequence: int
    event: CodexAgentRealtimeEvent
    received_at: datetime


@dataclass(frozen=True, slots=True)
class CodexAgentEventBufferSnapshot:
    """Phase 3 浏览器 hub 可消费的有界事件快照。"""

    events: list[BufferedCodexAgentEvent]
    gap_detected: bool


class CodexAgentEventBuffer:
    """接收完整产品事件；溢出时显式标记 snapshot required。"""

    def __init__(self, *, capacity: int) -> None:
        if capacity <= 0:
            raise ValueError("Agent事件缓冲容量必须大于零。")
        self._capacity = capacity
        self._events: dict[UUID, deque[BufferedCodexAgentEvent]] = {}
        self._sequences: dict[UUID, int] = {}
        self._gaps: set[UUID] = set()
        self._lock = asyncio.Lock()

    async def publish(
        self,
        event: CodexAgentRealtimeEvent,
        principal: AgentDevicePrincipal,
    ) -> bool:
        """按设备主体再次验证 host 后有界保存事件。"""

        if str(event.host_id) != principal.host_id:
            raise PermissionError("Agent事件host_id与设备凭据不匹配。")
        async with self._lock:
            sequence = self._sequences.get(event.host_id, 0) + 1
            self._sequences[event.host_id] = sequence
            events = self._events.setdefault(event.host_id, deque(maxlen=self._capacity))
            overflowed = len(events) == self._capacity and event.host_id not in self._gaps
            if overflowed:
                self._gaps.add(event.host_id)
            events.append(
                BufferedCodexAgentEvent(
                    sequence=sequence,
                    event=event,
                    received_at=datetime.now(UTC),
                )
            )
            return overflowed

    async def read(self, host_id: UUID) -> CodexAgentEventBufferSnapshot:
        """读取当前有界窗口，不清除 gap 事实。"""

        async with self._lock:
            return CodexAgentEventBufferSnapshot(
                events=list(self._events.get(host_id, ())),
                gap_detected=host_id in self._gaps,
            )
