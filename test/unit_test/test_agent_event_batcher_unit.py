"""Agent 上游实时批处理窗口和字节阈值测试。"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from src.core.codex_contract.agent_protocol_v2_contract import (
    AgentEventRecord,
    AgentItemDeltaEventDetail,
    AgentProtocolWarningEventDetail,
)
from src.core.codex_contract.app_server_schema_manifest_contract import (
    AppServerNotificationName,
)
from src.infrastructure.codex_agent.agent_event_batcher import AgentEventBatcher


def _delta_event(*, sequence: int, text: str) -> AgentEventRecord:
    """构造具有同一 epoch 的确定性 delta 事件。"""

    event_epoch = UUID("00000000-0000-0000-0000-000000000001")
    return AgentEventRecord(
        agent_event_epoch=event_epoch,
        seq=sequence,
        event_id=uuid4(),
        app_server_instance_id=UUID("00000000-0000-0000-0000-000000000002"),
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        detail=AgentItemDeltaEventDetail(
            method=AppServerNotificationName.AGENT_MESSAGE_DELTA,
            thread_id="thread-1",
            turn_id="turn-1",
            item_id="item-1",
            delta=text,
        ),
    )


def _barrier_event(*, sequence: int) -> AgentEventRecord:
    """构造必须先刷新前序 delta 的协议屏障事件。"""

    event_epoch = UUID("00000000-0000-0000-0000-000000000001")
    return AgentEventRecord(
        agent_event_epoch=event_epoch,
        seq=sequence,
        event_id=uuid4(),
        app_server_instance_id=UUID("00000000-0000-0000-0000-000000000002"),
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        detail=AgentProtocolWarningEventDetail(reason_code="app_server.warning"),
    )


def test_batcher_when_delta_exceeds_utf8_limit_should_flush() -> None:
    batcher = AgentEventBatcher(max_bytes=5)

    result = batcher.push(_delta_event(sequence=1, text="你你"))

    assert len(result.flushed) == 1
    assert result.flushed[0].first_seq == 1
    assert result.flushed[0].last_seq == 1


def test_batcher_when_window_elapsed_should_flush_pending_before_new_delta() -> None:
    batcher = AgentEventBatcher()
    initial = datetime(2026, 1, 1, tzinfo=UTC)
    batcher.push(_delta_event(sequence=1, text="first"), now=initial)

    result = batcher.push(
        _delta_event(sequence=2, text="second"),
        now=initial + timedelta(milliseconds=25),
    )

    assert len(result.flushed) == 1
    assert result.flushed[0].events[0].seq == 1
    assert batcher.has_pending is True


def test_batcher_when_barrier_arrives_should_flush_deltas_before_barrier() -> None:
    """屏障不能与前序 delta 合并，确保终态和错误不会被延后发送。"""

    batcher = AgentEventBatcher()
    batcher.push(_delta_event(sequence=1, text="streaming"))

    result = batcher.push(_barrier_event(sequence=2))

    assert [batch.first_seq for batch in result.flushed] == [1, 2]
    assert [batch.last_seq for batch in result.flushed] == [1, 2]
    assert batcher.has_pending is False
