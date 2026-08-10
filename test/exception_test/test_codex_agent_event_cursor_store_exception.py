"""Codex Agent 事件游标异常测试。"""

from __future__ import annotations

from uuid import uuid4

import pytest

from src.core.distributed_state_contract.atomic_state_contract import AtomicStateRecord
from src.infrastructure.codex.codex_agent_event_cursor_store import CodexAgentEventCursorStore
from src.infrastructure.distributed_state.memory_atomic_state import MemoryAtomicState


@pytest.mark.asyncio
async def test_load_or_start_when_corrupted_state_should_raise_contract_error() -> None:
    """验证损坏的原子状态不会被静默当作空游标。"""

    state = MemoryAtomicState()
    store = CodexAgentEventCursorStore(state=state)
    host_id = uuid4()
    await state.create(
        AtomicStateRecord(
            key=f"codex:agent_event_cursor:{host_id}",
            value='{"invalid":true}',
            version=1,
        )
    )

    with pytest.raises(ValueError, match="游标状态不符合契约"):
        await store.load_or_start(host_id=host_id, event_epoch=uuid4())
