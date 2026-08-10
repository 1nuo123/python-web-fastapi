"""Codex Agent 事件游标边界测试。"""

from __future__ import annotations

from uuid import uuid4

import pytest

from src.infrastructure.codex.codex_agent_event_cursor_store import CodexAgentEventCursorStore
from src.infrastructure.distributed_state.memory_atomic_state import MemoryAtomicState


@pytest.mark.asyncio
async def test_advance_when_zero_sequence_should_keep_initial_ack() -> None:
    """验证零序号 ACK 不会产生负向或虚假推进。"""

    state = MemoryAtomicState()
    store = CodexAgentEventCursorStore(state=state)
    host_id = uuid4()
    event_epoch = uuid4()

    await store.load_or_start(host_id=host_id, event_epoch=event_epoch)

    assert await store.advance(host_id=host_id, event_epoch=event_epoch, after_seq=0) == 0
