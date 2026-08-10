"""Codex长期双向连接会话单元测试。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import pytest

from src.core.codex_contract.connection_session_contract import (
    CodexConnectionFrame,
    CodexConnectionSessionInactiveError,
    CodexConnectionSlowConsumerError,
    CodexConnectionTransportClosed,
    CodexOutboundFrameSenderPort,
)
from src.infrastructure.codex.codex_connection_session import (
    CODEX_CONNECTION_INTERNAL_ERROR_CLOSE_CODE,
    CODEX_CONNECTION_NORMAL_CLOSE_CODE,
    CodexConnectionSessionPolicy,
    CodexDuplexConnectionSession,
)


class FakeCodexConnectionTransport:
    """使用内存队列模拟长期双向文本传输。"""

    def __init__(self, *, expected_sent_count: int = 1, block_sends: bool = False) -> None:
        self.incoming: asyncio.Queue[str | None] = asyncio.Queue()
        self.sent: list[str] = []
        self.expected_sent_count = expected_sent_count
        self.sent_event = asyncio.Event()
        self.send_gate = asyncio.Event()
        if not block_sends:
            self.send_gate.set()
        self.closed_code: int | None = None
        self.closed_reason: str | None = None

    async def receive_text(self) -> str:
        """读取测试入站帧。"""

        payload = await self.incoming.get()
        if payload is None:
            raise CodexConnectionTransportClosed()
        return payload

    async def send_text(self, payload: str) -> None:
        """记录测试出站帧。"""

        await self.send_gate.wait()
        self.sent.append(payload)
        if len(self.sent) >= self.expected_sent_count:
            self.sent_event.set()

    async def close(self, *, code: int, reason: str) -> None:
        """记录关闭语义。"""

        self.closed_code = code
        self.closed_reason = reason


class TestCodexConnectionSessionUnit:
    """长期连接多路消息、背压与生命周期测试。"""

    @pytest.mark.asyncio
    async def test_send_when_session_stopped_should_raise_connection_error(self) -> None:
        """验证停止的会话使用明确连接异常拒绝继续发送。"""

        session = self._build_session(
            transport=FakeCodexConnectionTransport(),
            handler=self._ignore_frame,
        )

        with pytest.raises(CodexConnectionSessionInactiveError):
            await session.send(
                CodexConnectionFrame(
                    message_id="stopped-session",
                    message_type="heartbeat",
                )
            )

    @pytest.mark.asyncio
    async def test_run_when_multiple_message_types_should_stay_active_until_shutdown(self) -> None:
        """验证一个连接可持续双向处理多类消息且不随单次操作完成关闭。"""

        transport = FakeCodexConnectionTransport(expected_sent_count=2)
        received_types: list[str] = []

        async def handle(
            frame: CodexConnectionFrame,
            sender: CodexOutboundFrameSenderPort,
        ) -> None:
            received_types.append(frame.message_type)
            await sender.send(
                CodexConnectionFrame(
                    message_id=f"reply-{frame.message_id}",
                    message_type=f"{frame.message_type}.ack",
                    payload={"accepted": True},
                )
            )

        shutdown_event = asyncio.Event()
        session = self._build_session(transport=transport, handler=handle)
        run_task = asyncio.create_task(session.run(shutdown_event=shutdown_event))
        await transport.incoming.put(self._frame_json("1", "heartbeat"))
        await transport.incoming.put(self._frame_json("2", "command.start"))

        await asyncio.wait_for(transport.sent_event.wait(), timeout=1)

        assert received_types == ["heartbeat", "command.start"]
        assert run_task.done() is False
        assert session.running is True

        shutdown_event.set()
        await asyncio.wait_for(run_task, timeout=1)

        assert session.running is False
        assert transport.closed_code == CODEX_CONNECTION_NORMAL_CLOSE_CODE

    @pytest.mark.asyncio
    async def test_run_when_outbound_queue_stalls_should_fail_boundedly(self) -> None:
        """验证慢消费者不会造成无界出站内存。"""

        transport = FakeCodexConnectionTransport(block_sends=True)

        async def handle(
            frame: CodexConnectionFrame,
            sender: CodexOutboundFrameSenderPort,
        ) -> None:
            for index in range(3):
                await sender.send(
                    CodexConnectionFrame(
                        message_id=f"{frame.message_id}-{index}",
                        message_type="event.delta",
                    )
                )

        session = CodexDuplexConnectionSession(
            transport=transport,
            inbound_handler=handle,
            policy=CodexConnectionSessionPolicy(
                outbound_queue_capacity=1,
                max_frame_bytes=4096,
                send_enqueue_timeout_seconds=0.01,
            ),
        )
        await transport.incoming.put(self._frame_json("1", "burst"))

        with pytest.raises(CodexConnectionSlowConsumerError):
            await asyncio.wait_for(session.run(shutdown_event=asyncio.Event()), timeout=1)

        assert transport.closed_code == CODEX_CONNECTION_INTERNAL_ERROR_CLOSE_CODE

    def test_policy_when_capacity_is_not_positive_should_reject(self) -> None:
        """验证长期连接策略保持有界。"""

        with pytest.raises(ValueError):
            CodexConnectionSessionPolicy(
                outbound_queue_capacity=0,
                max_frame_bytes=4096,
                send_enqueue_timeout_seconds=1,
            )

    def _build_session(
        self,
        *,
        transport: FakeCodexConnectionTransport,
        handler: Callable[
            [CodexConnectionFrame, CodexOutboundFrameSenderPort],
            Awaitable[None],
        ],
    ) -> CodexDuplexConnectionSession:
        """构建测试长期连接会话。"""

        return CodexDuplexConnectionSession(
            transport=transport,
            inbound_handler=handler,
            policy=CodexConnectionSessionPolicy(
                outbound_queue_capacity=4,
                max_frame_bytes=4096,
                send_enqueue_timeout_seconds=0.1,
            ),
        )

    def _frame_json(self, message_id: str, message_type: str) -> str:
        """构建合法入站帧。"""

        return CodexConnectionFrame(
            message_id=message_id,
            message_type=message_type,
        ).model_dump_json()

    async def _ignore_frame(
        self,
        frame: CodexConnectionFrame,
        sender: CodexOutboundFrameSenderPort,
    ) -> None:
        """提供不产生副作用的入站处理器。"""

        _ = frame
        _ = sender
