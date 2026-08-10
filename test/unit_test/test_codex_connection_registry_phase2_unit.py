"""Codex Agent 连接注册表单元测试。"""

from __future__ import annotations

from uuid import uuid4

import pytest

from src.core.codex_contract.connection_session_contract import CodexConnectionFrame
from src.infrastructure.codex.codex_connection_registry import CodexConnectionRegistry


class RecordingSender:
    def __init__(self) -> None:
        self.frames: list[CodexConnectionFrame] = []

    async def send(self, frame: CodexConnectionFrame) -> None:
        self.frames.append(frame)


@pytest.mark.asyncio
async def test_register_when_same_host_reconnects_should_replace_epoch_and_stop_old_lease() -> None:
    registry = CodexConnectionRegistry(max_connected_agents=1)
    host_id = uuid4()
    first = await registry.register(host_id, RecordingSender())
    second_sender = RecordingSender()
    second = await registry.register(host_id, second_sender)

    assert first.shutdown_event.is_set()
    assert second.epoch == first.epoch + 1
    await registry.unregister(first)
    assert await registry.read(host_id) == second

    frame = CodexConnectionFrame(message_id="1", message_type="heartbeat", payload={})
    await registry.send(host_id, frame)
    assert second_sender.frames == [frame]
