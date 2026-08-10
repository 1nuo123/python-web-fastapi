"""Agent控制通道重连主路径测试。"""

from __future__ import annotations

import asyncio

import pytest

from src.infrastructure.codex_agent.agent_control_channel import AgentControlChannel

TEST_WAIT_TIMEOUT_SECONDS = 1.0


class TestAgentControlChannelReconnectPath:
    """覆盖握手确认到初始化发送的存活连接路径。"""

    @pytest.mark.asyncio
    async def test_wait_for_hello_ack_when_session_active_should_continue(self) -> None:
        """验证活跃会话收到握手确认后可继续初始化。"""

        channel = self._build_channel()
        session_gate = asyncio.Event()
        session_task = asyncio.create_task(session_gate.wait())
        channel._hello_ack_event.set()
        try:
            await asyncio.wait_for(
                channel._wait_for_hello_ack(session_task),
                timeout=TEST_WAIT_TIMEOUT_SECONDS,
            )

            assert session_task.done() is False
        finally:
            session_task.cancel()
            await asyncio.gather(session_task, return_exceptions=True)

    def _build_channel(self) -> AgentControlChannel:
        """构建只包含握手状态的控制通道。"""

        channel = object.__new__(AgentControlChannel)
        channel._hello_ack_event = asyncio.Event()
        return channel
