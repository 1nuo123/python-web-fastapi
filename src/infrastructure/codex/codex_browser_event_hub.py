"""按认证主体隔离的 Codex 浏览器实时事件 Hub。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import JsonValue

from src.core.codex_contract.realtime_batch_contract import (
    CODEX_REALTIME_BATCH_MAX_BYTES,
    CODEX_REALTIME_BATCH_MAX_EVENTS,
    CodexRealtimeBatch,
    is_codex_realtime_batch_barrier,
)
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
    queue: asyncio.Queue[CodexRealtimeBatch | CodexRealtimeEvent] = field(init=False)
    _queued_event_count: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        # 队列单位是批次，容量仍按事件数核算，避免一个 64 事件批次绕过慢消费者上限。
        self.queue = asyncio.Queue()

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

    def build_batch(
        self,
        events: tuple[CodexRealtimeEvent, ...],
        *,
        barrier: bool,
    ) -> CodexRealtimeBatch:
        """构造单 epoch 且游标边界明确的浏览器传输批次。"""

        if not events:
            raise ValueError("浏览器实时批次必须至少包含一个事件。")
        return CodexRealtimeBatch(
            stream_epoch=events[0].header.stream_epoch,
            first_cursor=events[0].header.cursor,
            last_cursor=events[-1].header.cursor,
            barrier=barrier,
            events=events,
        )

    async def take_batch(self) -> CodexRealtimeBatch:
        """读取一个待发送批次，并释放其占用的事件容量。"""

        payload = await self.queue.get()
        batch = (
            payload
            if isinstance(payload, CodexRealtimeBatch)
            else self.build_batch(
                (payload,),
                barrier=is_codex_realtime_batch_barrier(payload.header.detail_kind),
            )
        )
        self._queued_event_count = max(0, self._queued_event_count - len(batch.events))
        return batch

    def enqueue_batch(self, batch: CodexRealtimeBatch) -> bool:
        """把批次放入订阅队列；返回是否仍可保持无缺口的连续流。"""

        if self._queued_event_count + len(batch.events) > self.capacity:
            return False
        self.queue.put_nowait(batch)
        self._queued_event_count += len(batch.events)
        return True

    def replace_with_gap(self, gap: CodexRealtimeBatch) -> None:
        """清空无法恢复的滞后批次，只保留要求快照的屏障事件。"""

        while not self.queue.empty():
            self.queue.get_nowait()
        self._queued_event_count = 0
        self.queue.put_nowait(gap)
        self._queued_event_count = len(gap.events)

    def build_bounded_batches(
        self,
        events: tuple[CodexRealtimeEvent, ...],
    ) -> tuple[CodexRealtimeBatch, ...]:
        """按屏障、64 事件和 64KiB 边界切分已分配游标的事件。"""

        batches: list[CodexRealtimeBatch] = []
        current: list[CodexRealtimeEvent] = []
        for event in events:
            if is_codex_realtime_batch_barrier(event.header.detail_kind):
                if current:
                    batches.append(self.build_batch(tuple(current), barrier=False))
                    current.clear()
                batches.append(self.build_batch((event,), barrier=True))
                continue
            if current and self._would_exceed_batch_limit(current, event):
                batches.append(self.build_batch(tuple(current), barrier=False))
                current.clear()
            current.append(event)
        if current:
            batches.append(self.build_batch(tuple(current), barrier=False))
        return tuple(batches)

    @staticmethod
    def _would_exceed_batch_limit(
        current: list[CodexRealtimeEvent],
        candidate: CodexRealtimeEvent,
    ) -> bool:
        """候选事件跨越传输上限时必须留到下一批，单事件过大时仍可独立发送。"""

        if len(current) >= CODEX_REALTIME_BATCH_MAX_EVENTS:
            return True
        candidate_batch = CodexRealtimeBatch(
            stream_epoch=current[0].header.stream_epoch,
            first_cursor=current[0].header.cursor,
            last_cursor=candidate.header.cursor,
            events=tuple((*current, candidate)),
        )
        return (
            len(candidate_batch.model_dump_json().encode("utf-8")) > CODEX_REALTIME_BATCH_MAX_BYTES
        )


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
        self._publication_lock = asyncio.Lock()
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
        """兼容单事件调用方，并通过统一批接口完成 fan-out。"""

        await self.publish_batch(subject_id, (event,))

    async def publish_batch(
        self,
        subject_id: str,
        events: tuple[CodexProductEvent, ...],
    ) -> None:
        """为一个 owner 构造有序批次，并把相同批次投递给每个标签页。"""

        if not events:
            return
        async with self._publication_lock:
            async with self._lock:
                if not self._accepting:
                    return
                subscriptions = tuple(self._subscriptions.get(subject_id, ()))
            realtime_events = tuple(self._build_product_event(event) for event in events)
            realtime_events = await self._assign_cursors(subject_id, realtime_events)
            if not realtime_events:
                return
            for subscription in subscriptions:
                for batch in subscription.build_bounded_batches(realtime_events):
                    self._enqueue_batch(subscription, batch)

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
        self._enqueue_batch(
            subscription,
            subscription.build_batch(
                (event,),
                barrier=is_codex_realtime_batch_barrier(event.header.detail_kind),
            ),
        )

    async def shutdown(self) -> None:
        async with self._publication_lock:
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

    async def _assign_cursors(
        self,
        subject_id: str,
        events: tuple[CodexRealtimeEvent, ...],
    ) -> tuple[CodexRealtimeEvent, ...]:
        """按输入顺序写入分布式流，令实时批次与重放游标完全一致。"""

        if self._distributed_stream is None:
            return events
        assigned_events: list[CodexRealtimeEvent] = []
        for event in events:
            cursor = await self._distributed_stream.append(
                owner_subject_id=subject_id,
                event=event,
            )
            assigned_events.append(
                event.model_copy(
                    update={"header": event.header.model_copy(update={"cursor": cursor})}
                )
            )
        return tuple(assigned_events)

    def _enqueue_batch(
        self,
        subscription: CodexBrowserSubscription,
        batch: CodexRealtimeBatch,
    ) -> None:
        if subscription.enqueue_batch(batch):
            return
        last_event = batch.events[-1]
        gap_event = subscription.build_local_event(
            event_type=CodexRealtimeEventType.STREAM_GAP_DETECTED,
            host_id=last_event.header.host_id,
            workspace_id=last_event.header.workspace_id,
            thread_id=last_event.header.thread_id,
            turn_id=last_event.header.turn_id,
            payload={
                "reason": "browser_queue_overflow",
                "server_time": datetime.now(UTC).isoformat(),
            },
        )
        subscription.replace_with_gap(subscription.build_batch((gap_event,), barrier=True))
