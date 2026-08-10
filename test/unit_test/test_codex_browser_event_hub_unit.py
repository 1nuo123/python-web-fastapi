"""Codex 浏览器事件 Hub 容量与慢消费者单元测试。"""

from uuid import uuid4

import pytest

from src.application.codex.codex_protocol_mapper import CodexProductEvent
from src.core.codex_contract.realtime_event_contract import CodexRealtimeEventType
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
                payload={"delta": str(index)},
            ),
        )

    assert subscription.queue.qsize() == 1
    gap = subscription.queue.get_nowait()
    assert gap.type is CodexRealtimeEventType.STREAM_GAP_DETECTED
    assert gap.payload["reason"] == "browser_queue_overflow"
    assert gap.cursor is None
    assert gap.event_id


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
