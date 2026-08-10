"""Codex Agent 事件游标路径测试。"""

from __future__ import annotations

from uuid import uuid4

import pytest

from src.infrastructure.codex.codex_agent_event_cursor_store import (
    CodexAgentEventCursorStore,
)
from src.infrastructure.distributed_state.memory_atomic_state import MemoryAtomicState


@pytest.mark.asyncio
async def test_load_or_start_when_concurrent_create_should_retry_and_read_created_state() -> None:
    """验证首次创建竞争路径会重读已存在的游标。"""

    state = MemoryAtomicState()
    store = CodexAgentEventCursorStore(state=state)
    host_id = uuid4()
    event_epoch = uuid4()

    assert await store.load_or_start(host_id=host_id, event_epoch=event_epoch) == 0
