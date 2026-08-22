"""Codex 浏览器事件 Hub 容量与慢消费者单元测试。"""

from typing import cast
from uuid import uuid4

import pytest

from src.application.codex.codex_protocol_mapper import CodexProductEvent
from src.core.codex_contract.realtime_batch_contract import CodexRealtimeBatch
from src.core.codex_contract.realtime_event_contract import (
    CodexRealtimeEventType,
    CodexStreamGapDetail,
)
from src.infrastructure.codex.codex_browser_event_hub import CodexBrowserEventHub


@pytest.mark.asyncio
async def test_publish_when_slow_consumer_overflows_should_replace_queue_with_gap() -> None:
    host_id = uuid4()
    hub = CodexBrowserEventHub(queue_capacity=2)
    subscription = await hub.subscribe("owner-1")

    for index in range(3):
        await hub.publish(
            "owner-1",
            CodexProductEvent(
                host_id=host_id,
                workspace_id=None,
                thread_id="thread-1",
                turn_id="turn-1",
                item_id="item-1",
                event_type=CodexRealtimeEventType.ITEM_DELTA,
                payload={
                    "item_id": "item-1",
                    "thread_id": "thread-1",
                    "turn_id": "turn-1",
                    "delta": str(index),
                },
            ),
        )

    assert subscription.queue.qsize() == 1
    gap_batch = cast(CodexRealtimeBatch, subscription.queue.get_nowait())
    assert gap_batch.barrier is True
    assert len(gap_batch.events) == 1
    gap = gap_batch.events[0]
    assert gap.header.detail_kind is CodexRealtimeEventType.STREAM_GAP_DETECTED
    assert cast(CodexStreamGapDetail, gap.detail).reason == "browser_queue_overflow"
    assert gap.header.cursor is None
    assert gap.header.event_id


@pytest.mark.asyncio
async def test_publish_when_other_owner_subscribed_should_keep_subject_isolated() -> None:
    hub = CodexBrowserEventHub(queue_capacity=2)
    owner = await hub.subscribe("owner-1")
    other = await hub.subscribe("owner-2")

    await hub.publish(
        "owner-1",
        CodexProductEvent(
            host_id=uuid4(),
            workspace_id=None,
            thread_id=None,
            turn_id=None,
            item_id=None,
            event_type=CodexRealtimeEventType.PROTOCOL_WARNING,
            payload={"warning": "bounded"},
        ),
    )

    assert owner.queue.qsize() == 1
    assert other.queue.empty()


@pytest.mark.asyncio
async def test_subscription_should_build_same_epoch_batch_with_cursor_boundaries() -> None:
    hub = CodexBrowserEventHub(queue_capacity=2)
    subscription = await hub.subscribe("owner-1")
    host_id = uuid4()
    first = subscription.build_local_event(
        event_type=CodexRealtimeEventType.PROTOCOL_WARNING,
        host_id=host_id,
        payload={"warning": "first"},
    ).model_copy(
        update={
            "header": subscription.build_local_event(
                event_type=CodexRealtimeEventType.PROTOCOL_WARNING,
                host_id=host_id,
                payload={"warning": "unused"},
            ).header.model_copy(update={"cursor": "1"})
        }
    )
    last = first.model_copy(update={"header": first.header.model_copy(update={"cursor": "2"})})

    batch = subscription.build_batch((first, last), barrier=False)

    assert batch.first_cursor == "1"
    assert batch.last_cursor == "2"


@pytest.mark.asyncio
async def test_publish_batch_should_fan_out_ordered_batches_and_isolate_barrier() -> None:
    """同一 owner 的产品事件应以普通批次和独立 barrier 批次入队。"""

    host_id = uuid4()
    hub = CodexBrowserEventHub(queue_capacity=10)
    subscription = await hub.subscribe("owner-batch")
    events = tuple(
        CodexProductEvent(
            host_id=host_id,
            workspace_id=None,
            thread_id="thread-1",
            turn_id="turn-1",
            item_id="item-1",
            event_type=event_type,
            payload=(
                {
                    "item_id": "item-1",
                    "thread_id": "thread-1",
                    "turn_id": "turn-1",
                    "delta": "a",
                }
                if event_type is CodexRealtimeEventType.ITEM_DELTA
                else {"warning": "done"}
            ),
        )
        for event_type in (
            CodexRealtimeEventType.ITEM_DELTA,
            CodexRealtimeEventType.PROTOCOL_WARNING,
        )
    )

    await hub.publish_batch("owner-batch", events)

    normal = cast(CodexRealtimeBatch, subscription.queue.get_nowait())
    barrier = cast(CodexRealtimeBatch, subscription.queue.get_nowait())
    assert len(normal.events) == 1
    assert normal.barrier is False
    assert normal.events[0].header.detail_kind is CodexRealtimeEventType.ITEM_DELTA
    assert barrier.barrier is True
    assert barrier.events[0].header.detail_kind is CodexRealtimeEventType.PROTOCOL_WARNING
