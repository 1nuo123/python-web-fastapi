"""Codex Agent 事件游标存储单元测试。"""

from __future__ import annotations

from uuid import uuid4

import pytest

from src.infrastructure.codex.codex_agent_event_cursor_store import (
    CodexAgentEventCursorStore,
    CodexAgentEventEpochConflictError,
)
from src.infrastructure.distributed_state.memory_atomic_state import MemoryAtomicState


class TestCodexAgentEventCursorStoreUnit:
    """验证事件 epoch 与累计 ACK 的基本语义。"""

    @pytest.mark.asyncio
    async def test_load_or_start_when_same_epoch_should_preserve_ack(self) -> None:
        state = MemoryAtomicState()
        store = CodexAgentEventCursorStore(state=state)
        host_id = uuid4()
        event_epoch = uuid4()

        assert await store.load_or_start(host_id=host_id, event_epoch=event_epoch) == 0
        assert await store.advance(host_id=host_id, event_epoch=event_epoch, after_seq=3) == 3
        assert await store.load_or_start(host_id=host_id, event_epoch=event_epoch) == 3

    @pytest.mark.asyncio
    async def test_advance_when_lower_sequence_should_keep_current_ack(self) -> None:
        state = MemoryAtomicState()
        store = CodexAgentEventCursorStore(state=state)
        host_id = uuid4()
        event_epoch = uuid4()

        await store.load_or_start(host_id=host_id, event_epoch=event_epoch)
        await store.advance(host_id=host_id, event_epoch=event_epoch, after_seq=5)

        assert await store.advance(host_id=host_id, event_epoch=event_epoch, after_seq=2) == 5

    @pytest.mark.asyncio
    async def test_advance_when_epoch_changed_should_reject_old_connection(self) -> None:
        state = MemoryAtomicState()
        store = CodexAgentEventCursorStore(state=state)
        host_id = uuid4()
        old_epoch = uuid4()
        new_epoch = uuid4()

        await store.load_or_start(host_id=host_id, event_epoch=old_epoch)
        await store.advance(host_id=host_id, event_epoch=old_epoch, after_seq=4)
        await store.load_or_start(host_id=host_id, event_epoch=new_epoch)

        with pytest.raises(CodexAgentEventEpochConflictError):
            await store.advance(host_id=host_id, event_epoch=old_epoch, after_seq=5)
