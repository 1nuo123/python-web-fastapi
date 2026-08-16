"""Agent控制通道重连异常测试。"""

from __future__ import annotations

import asyncio

import pytest

from src.core.codex_contract.connection_session_contract import (
    CodexConnectionTransportClosed,
)
from src.infrastructure.codex_agent.agent_control_channel import AgentControlChannel

TEST_WAIT_TIMEOUT_SECONDS = 1.0


class TestAgentControlChannelReconnectException:
    """覆盖握手阶段连接提前关闭与内部失败。"""

    @pytest.mark.asyncio
    async def test_wait_for_hello_ack_when_session_closed_should_request_reconnect(self) -> None:
        """验证握手确认前正常断线转换为可重试连接异常。"""

        channel = self._build_channel()
        session_task = asyncio.create_task(asyncio.sleep(0))

        with pytest.raises(CodexConnectionTransportClosed):
            await asyncio.wait_for(
                channel._wait_for_hello_ack(session_task),
                timeout=TEST_WAIT_TIMEOUT_SECONDS,
            )

        assert session_task.done() is True

    @pytest.mark.asyncio
    async def test_wait_for_hello_ack_when_session_failed_should_preserve_cause(self) -> None:
        """验证会话内部错误不会被替换成笼统生命周期错误。"""

        channel = self._build_channel()

        async def fail_session() -> None:
            raise ConnectionError("控制面接收循环失败。")

        session_task = asyncio.create_task(fail_session())

        with pytest.raises(ConnectionError, match="控制面接收循环失败"):
            await asyncio.wait_for(
                channel._wait_for_hello_ack(session_task),
                timeout=TEST_WAIT_TIMEOUT_SECONDS,
            )

        assert session_task.done() is True

    def test_connected_session_when_remote_closes_should_request_backoff_retry(self) -> None:
        """验证已完成握手的连接意外结束时不会立即重新连接。"""

        channel = self._build_channel()
        channel._shutdown_event = asyncio.Event()

        with pytest.raises(CodexConnectionTransportClosed, match="退避策略重连"):
            channel._raise_if_connection_closed_unexpectedly()

    def _build_channel(self) -> AgentControlChannel:
        """构建只包含握手状态的控制通道。"""

        channel = object.__new__(AgentControlChannel)
        channel._hello_ack_event = asyncio.Event()
        return channel
