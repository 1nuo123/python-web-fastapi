"""按认证主体隔离的 Codex 浏览器实时事件 Hub。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import JsonValue

from src.core.codex_contract.realtime_event_contract import (
    CodexRealtimeDetailFactory,
    CodexRealtimeEvent,
    CodexRealtimeEventHeader,
    CodexRealtimeEventType,
)
from src.infrastructure.codex.codex_protocol_mapper import CodexProductEvent
from src.infrastructure.codex.codex_realtime_stream_adapter import (
    CodexRealtimeStreamAdapter,
)


@dataclass(eq=False, slots=True)
class CodexBrowserSubscription:
    """单个浏览器连接自己的有界本地 fan-out 队列。"""

    subject_id: str
    capacity: int
    queue: asyncio.Queue[CodexRealtimeEvent] = field(init=False)

    def __post_init__(self) -> None:
        self.queue = asyncio.Queue(maxsize=self.capacity)

    def build_local_event(
        self,
        *,
        event_type: CodexRealtimeEventType,
        host_id: UUID,
        payload: dict[str, JsonValue],
        workspace_id: UUID | None = None,
        thread_id: str | None = None,
        turn_id: str | None = None,
        item_id: str | None = None,
    ) -> CodexRealtimeEvent:
        detail = CodexRealtimeDetailFactory().build(event_type, payload)
        event = CodexRealtimeEvent(
            header=CodexRealtimeEventHeader(
                event_id=str(uuid4()),
                occurred_at=datetime.now(UTC),
                host_id=host_id,
                workspace_id=workspace_id,
                thread_id=thread_id,
                turn_id=turn_id,
                item_id=item_id,
                detail_kind=event_type,
            ),
            detail=detail,
        )
        return event


class CodexBrowserEventHub:
    """发布前绑定服务端所有者，慢消费者溢出时显式要求 snapshot。"""

    def __init__(
        self,
        *,
        queue_capacity: int,
        distributed_stream: CodexRealtimeStreamAdapter | None = None,
    ) -> None:
        if queue_capacity <= 1:
            raise ValueError("浏览器事件队列容量必须大于一。")
        self._queue_capacity = queue_capacity
        self._subscriptions: dict[str, set[CodexBrowserSubscription]] = {}
        self._lock = asyncio.Lock()
        self._accepting = True
        self._distributed_stream = distributed_stream

    async def subscribe(self, subject_id: str) -> CodexBrowserSubscription:
        async with self._lock:
            if not self._accepting:
                raise RuntimeError("Codex浏览器事件Hub正在停止。")
            subscription = CodexBrowserSubscription(subject_id, self._queue_capacity)
            self._subscriptions.setdefault(subject_id, set()).add(subscription)
            return subscription

    async def unsubscribe(self, subscription: CodexBrowserSubscription) -> None:
        async with self._lock:
            subscriptions = self._subscriptions.get(subscription.subject_id)
            if subscriptions is None:
                return
            subscriptions.discard(subscription)
            if not subscriptions:
                self._subscriptions.pop(subscription.subject_id, None)

    async def publish(self, subject_id: str, event: CodexProductEvent) -> None:
        async with self._lock:
            subscriptions = tuple(self._subscriptions.get(subject_id, ()))
        realtime_event = self._build_product_event(event)
        if self._distributed_stream is not None:
            cursor = await self._distributed_stream.append(
                owner_subject_id=subject_id,
                event=realtime_event,
            )
            realtime_event = realtime_event.model_copy(
                update={"header": realtime_event.header.model_copy(update={"cursor": cursor})}
            )
        for subscription in subscriptions:
            self._enqueue(subscription, realtime_event)

    def enqueue_local(
        self,
        subscription: CodexBrowserSubscription,
        *,
        event_type: CodexRealtimeEventType,
        host_id: UUID,
        payload: dict[str, JsonValue],
    ) -> None:
        event = subscription.build_local_event(
            event_type=event_type,
            host_id=host_id,
            payload=payload,
        )
        self._enqueue(subscription, event)

    async def shutdown(self) -> None:
        async with self._lock:
            self._accepting = False
            self._subscriptions.clear()

    def _build_product_event(
        self,
        product_event: CodexProductEvent,
    ) -> CodexRealtimeEvent:
        return CodexRealtimeEvent(
            header=CodexRealtimeEventHeader(
                event_id=str(uuid4()),
                occurred_at=product_event.occurred_at or datetime.now(UTC),
                detail_kind=product_event.event_type,
                host_id=product_event.host_id,
                workspace_id=product_event.workspace_id,
                thread_id=product_event.thread_id,
                turn_id=product_event.turn_id,
                item_id=product_event.item_id,
            ),
            detail=CodexRealtimeDetailFactory().build(
                product_event.event_type,
                product_event.payload,
            ),
        )

    def _enqueue(
        self,
        subscription: CodexBrowserSubscription,
        event: CodexRealtimeEvent,
    ) -> None:
        if not subscription.queue.full():
            subscription.queue.put_nowait(event)
            return
        while not subscription.queue.empty():
            subscription.queue.get_nowait()
        gap = subscription.build_local_event(
            event_type=CodexRealtimeEventType.STREAM_GAP_DETECTED,
            host_id=event.header.host_id,
            workspace_id=event.header.workspace_id,
            thread_id=event.header.thread_id,
            turn_id=event.header.turn_id,
            payload={
                "reason": "browser_queue_overflow",
                "server_time": datetime.now(UTC).isoformat(),
            },
        )
        subscription.queue.put_nowait(gap)
