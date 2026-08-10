"""Agent控制通道重连边界测试。"""

from __future__ import annotations

import asyncio

import pytest

from src.core.codex_contract.connection_session_contract import (
    CodexConnectionTransportClosed,
)
from src.infrastructure.codex_agent.agent_control_channel import AgentControlChannel

TEST_WAIT_TIMEOUT_SECONDS = 1.0


class TestAgentControlChannelReconnectBoundary:
    """覆盖握手确认与连接关闭同时发生的竞态边界。"""

    @pytest.mark.asyncio
    async def test_wait_for_hello_ack_when_ack_and_close_coincide_should_reconnect(self) -> None:
        """验证已确认但已关闭的代次不会继续发送快照。"""

        channel = object.__new__(AgentControlChannel)
        channel._hello_ack_event = asyncio.Event()
        channel._hello_ack_event.set()
        session_task = asyncio.create_task(asyncio.sleep(0))
        await session_task

        with pytest.raises(CodexConnectionTransportClosed):
            await asyncio.wait_for(
                channel._wait_for_hello_ack(session_task),
                timeout=TEST_WAIT_TIMEOUT_SECONDS,
            )

        assert session_task.done() is True

    @pytest.mark.asyncio
    async def test_require_active_session_when_task_pending_should_return(self) -> None:
        """验证尚未结束的会话不会被误判为断线。"""

        channel = object.__new__(AgentControlChannel)
        session_gate = asyncio.Event()
        session_task = asyncio.create_task(session_gate.wait())
        try:
            await asyncio.wait_for(
                channel._require_active_session(session_task),
                timeout=TEST_WAIT_TIMEOUT_SECONDS,
            )
        finally:
            session_task.cancel()
            await asyncio.gather(session_task, return_exceptions=True)

        assert session_task.cancelled() is True
