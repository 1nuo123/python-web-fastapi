"""Codex 浏览器 WebSocket 单写者关闭竞态单元测试。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import pytest
from starlette.websockets import WebSocket, WebSocketDisconnect, WebSocketState

from src.api.endpoint_codex_control.route_codex_realtime import (
    CODEX_REALTIME_BATCH_MAX_BYTES,
    CODEX_REALTIME_BATCH_MAX_EVENTS,
    CodexBrowserRealtimeSession,
)
from src.core.codex_contract.realtime_event_contract import (
    CodexItemDeltaDetail,
    CodexRealtimeEventType,
)
from src.infrastructure.codex.codex_browser_event_hub import CodexBrowserEventHub
from src.infrastructure.codex.codex_control_runtime import CodexControlRuntime

TEST_HOST_ID = UUID("00000000-0000-0000-0000-000000000001")
TEST_HEARTBEAT_SECONDS = 60


@dataclass(slots=True)
class CodexRealtimeSettingsStub:
    """实时会话测试只需要心跳间隔。"""

    agent_heartbeat_seconds: int = TEST_HEARTBEAT_SECONDS


@dataclass(slots=True)
class CodexRealtimeRuntimeStub:
    """实时会话测试使用的最小运行时。"""

    settings: CodexRealtimeSettingsStub = field(default_factory=CodexRealtimeSettingsStub)


class BlockingWebSocketStub:
    """允许精确制造发送中断开的 WebSocket 替身。"""

    def __init__(self) -> None:
        self.client_state = WebSocketState.CONNECTED
        self.application_state = WebSocketState.CONNECTED
        self.send_started = asyncio.Event()
        self.send_release = asyncio.Event()
        self.receive_queue: asyncio.Queue[str | None] = asyncio.Queue()
        self.sent_texts: list[str] = []
        self.active_writers = 0
        self.maximum_active_writers = 0

    async def send_text(self, text: str) -> None:
        """阻塞唯一写者，断开后模拟 Starlette 的发送异常。"""

        self.active_writers += 1
        self.maximum_active_writers = max(
            self.maximum_active_writers,
            self.active_writers,
        )
        self.send_started.set()
        try:
            await self.send_release.wait()
            if self.client_state is WebSocketState.DISCONNECTED:
                raise RuntimeError("WebSocket已经关闭，禁止继续发送。")
            self.sent_texts.append(text)
        finally:
            self.active_writers -= 1

    async def receive_text(self) -> str:
        """等待测试驱动的客户端消息或断开信号。"""

        received = await self.receive_queue.get()
        if received is None:
            raise WebSocketDisconnect(code=1000)
        return received

    async def disconnect(self) -> None:
        """切换双方状态并唤醒断开监听任务。"""

        self.client_state = WebSocketState.DISCONNECTED
        self.application_state = WebSocketState.DISCONNECTED
        await self.receive_queue.put(None)


class CancelledReceiveWebSocketStub(BlockingWebSocketStub):
    """模拟测试客户端关闭时监听协程直接收到取消。"""

    async def receive_text(self) -> str:
        """以取消结束断开监听，验证会话不会向外泄漏取消异常。"""

        raise asyncio.CancelledError


class TestCodexBrowserRealtimeSessionUnit:
    """验证发送与断开同时发生时的任务回收。"""

    @pytest.mark.asyncio
    async def test_session_when_disconnect_during_send_should_stop_writer_and_release_tasks(
        self,
    ) -> None:
        """发送中的断开应正常收敛，不产生第二写者或遗留任务。"""

        hub = CodexBrowserEventHub(queue_capacity=2)
        subscription = await hub.subscribe("subject-realtime-session")
        websocket = BlockingWebSocketStub()
        runtime = cast(CodexControlRuntime, CodexRealtimeRuntimeStub())
        session = CodexBrowserRealtimeSession(
            websocket=cast(WebSocket, websocket),
            subscription=subscription,
            runtime=runtime,
        )
        subscription.queue.put_nowait(
            subscription.build_local_event(
                event_type=CodexRealtimeEventType.CONNECTION_READY,
                host_id=TEST_HOST_ID,
                payload={
                    "heartbeat_interval": TEST_HEARTBEAT_SECONDS,
                    "server_time": datetime.now(UTC).isoformat(),
                },
            )
        )
        run_task = asyncio.create_task(session.run())
        try:
            await asyncio.wait_for(websocket.send_started.wait(), timeout=1)
            await websocket.disconnect()
            websocket.send_release.set()
            await asyncio.wait_for(run_task, timeout=1)
            await session.close()
            await session.close()

            assert websocket.sent_texts == []
            assert websocket.active_writers == 0
            assert websocket.maximum_active_writers == 1
            assert run_task.done()
            assert not run_task.cancelled()
        finally:
            websocket.send_release.set()
            if not run_task.done():
                run_task.cancel()
                await asyncio.gather(run_task, return_exceptions=True)
            await hub.unsubscribe(subscription)
            await hub.shutdown()

    @pytest.mark.asyncio
    async def test_session_when_disconnect_listener_is_cancelled_should_close_normally(
        self,
    ) -> None:
        """客户端关闭触发的监听取消应作为正常生命周期边界处理。"""

        hub = CodexBrowserEventHub(queue_capacity=2)
        subscription = await hub.subscribe("subject-realtime-cancelled-listener")
        websocket = CancelledReceiveWebSocketStub()
        runtime = cast(CodexControlRuntime, CodexRealtimeRuntimeStub())
        session = CodexBrowserRealtimeSession(
            websocket=cast(WebSocket, websocket),
            subscription=subscription,
            runtime=runtime,
        )
        try:
            await asyncio.wait_for(session.run(), timeout=1)

            assert websocket.active_writers == 0
            assert websocket.sent_texts == []
        finally:
            websocket.send_release.set()
            await session.close()
            await hub.unsubscribe(subscription)
            await hub.shutdown()

    @pytest.mark.asyncio
    async def test_collect_batch_should_defer_event_that_exceeds_byte_limit(self) -> None:
        """64KiB 边界前的候选事件必须留给下一批，不能构造超限批次。"""

        hub = CodexBrowserEventHub(queue_capacity=4)
        subscription = await hub.subscribe("subject-realtime-byte-limit")
        websocket = BlockingWebSocketStub()
        runtime = cast(CodexControlRuntime, CodexRealtimeRuntimeStub())
        session = CodexBrowserRealtimeSession(
            websocket=cast(WebSocket, websocket),
            subscription=subscription,
            runtime=runtime,
            batch_enabled=True,
        )
        try:
            for item_id, delta in (
                ("item-first", "a" * (CODEX_REALTIME_BATCH_MAX_BYTES // 2)),
                ("item-second", "b" * (CODEX_REALTIME_BATCH_MAX_BYTES // 2)),
            ):
                subscription.queue.put_nowait(
                    subscription.build_local_event(
                        event_type=CodexRealtimeEventType.ITEM_DELTA,
                        host_id=TEST_HOST_ID,
                        payload={
                            "item_id": item_id,
                            "thread_id": "thread-1",
                            "turn_id": "turn-1",
                            "delta": delta,
                        },
                    )
                )

            batch = await session._collect_batch(await session._next_event())
            deferred = await session._next_event()

            assert len(batch.events) == 1
            assert len(batch.model_dump_json().encode("utf-8")) <= (CODEX_REALTIME_BATCH_MAX_BYTES)
            assert isinstance(deferred.detail, CodexItemDeltaDetail)
            assert deferred.detail.item_id == "item-second"
        finally:
            await session.close()
            await hub.unsubscribe(subscription)
            await hub.shutdown()

    @pytest.mark.asyncio
    async def test_collect_batch_should_flush_at_event_limit_and_preserve_next_event(
        self,
    ) -> None:
        """第 65 个普通事件必须进入下一批，避免一次 reducer commit 失去上界。"""

        hub = CodexBrowserEventHub(queue_capacity=CODEX_REALTIME_BATCH_MAX_EVENTS + 1)
        subscription = await hub.subscribe("subject-realtime-event-limit")
        websocket = BlockingWebSocketStub()
        runtime = cast(CodexControlRuntime, CodexRealtimeRuntimeStub())
        session = CodexBrowserRealtimeSession(
            websocket=cast(WebSocket, websocket),
            subscription=subscription,
            runtime=runtime,
            batch_enabled=True,
        )
        try:
            for index in range(CODEX_REALTIME_BATCH_MAX_EVENTS + 1):
                subscription.queue.put_nowait(
                    subscription.build_local_event(
                        event_type=CodexRealtimeEventType.CONNECTION_HEARTBEAT,
                        host_id=TEST_HOST_ID,
                        payload={"server_time": datetime.now(UTC).isoformat()},
                    )
                )

            batch = await session._collect_batch(await session._next_event())
            deferred = await session._next_event()

            assert len(batch.events) == CODEX_REALTIME_BATCH_MAX_EVENTS
            assert deferred.header.event_id not in {event.header.event_id for event in batch.events}
        finally:
            await session.close()
            await hub.unsubscribe(subscription)
            await hub.shutdown()

    @pytest.mark.asyncio
    async def test_collect_batch_should_flush_pending_events_before_barrier(self) -> None:
        """屏障事件必须单独输出，并保持前序普通事件的传输顺序。"""

        hub = CodexBrowserEventHub(queue_capacity=2)
        subscription = await hub.subscribe("subject-realtime-barrier")
        websocket = BlockingWebSocketStub()
        runtime = cast(CodexControlRuntime, CodexRealtimeRuntimeStub())
        session = CodexBrowserRealtimeSession(
            websocket=cast(WebSocket, websocket),
            subscription=subscription,
            runtime=runtime,
            batch_enabled=True,
        )
        try:
            subscription.queue.put_nowait(
                subscription.build_local_event(
                    event_type=CodexRealtimeEventType.CONNECTION_HEARTBEAT,
                    host_id=TEST_HOST_ID,
                    payload={"server_time": datetime.now(UTC).isoformat()},
                )
            )
            subscription.queue.put_nowait(
                subscription.build_local_event(
                    event_type=CodexRealtimeEventType.PROTOCOL_WARNING,
                    host_id=TEST_HOST_ID,
                    payload={"warning": "barrier"},
                )
            )

            normal = await session._collect_batch(await session._next_event())
            barrier = await session._collect_batch(await session._next_event())

            assert normal.barrier is False
            assert [event.header.detail_kind for event in normal.events] == [
                CodexRealtimeEventType.CONNECTION_HEARTBEAT
            ]
            assert barrier.barrier is True
            assert [event.header.detail_kind for event in barrier.events] == [
                CodexRealtimeEventType.PROTOCOL_WARNING
            ]
        finally:
            await session.close()
            await hub.unsubscribe(subscription)
            await hub.shutdown()
