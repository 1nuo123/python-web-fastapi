"""流状态存储与票据服务单元测试。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.application.streaming.stream_access_ticket_service import StreamAccessTicketService
from src.core.stream_contract.stream_access_contract import (
    StreamReplayEventRecord,
    StreamResumeRequest,
)
from src.infrastructure.streaming.memory_stream_state_store import MemoryStreamStateStore


class TestStreamStateStoreUnit:
    """内存流状态存储单元测试集合。"""

    @pytest.mark.asyncio
    async def test_ticket_should_only_be_consumed_once_and_match_binding(self) -> None:
        """验证票据绑定主体、操作、IP 且仅消费一次。"""

        store = MemoryStreamStateStore()
        await store.open()
        try:
            service = StreamAccessTicketService(state_store=store, ttl_seconds=30)
            ticket = await service.issue(
                subject_id="subject-1",
                operation_name="operation-1",
                client_ip="127.0.0.1",
            )

            assert await service.consume(
                ticket=ticket.detail.ticket,
                subject_id="subject-1",
                operation_name="operation-1",
                client_ip="127.0.0.1",
            )
            assert not await service.consume(
                ticket=ticket.detail.ticket,
                subject_id="subject-1",
                operation_name="operation-1",
                client_ip="127.0.0.1",
            )
        finally:
            await store.close()

    @pytest.mark.asyncio
    async def test_replay_window_should_return_events_after_last_event(self) -> None:
        """验证恢复窗口仅返回最后事件之后的有序记录。"""

        store = MemoryStreamStateStore()
        await store.open()
        now = datetime.now(UTC)
        try:
            for sequence in range(3):
                await store.append_event(
                    StreamReplayEventRecord(
                        stream_id="stream-1",
                        event_id=f"event-{sequence}",
                        sequence=sequence,
                        subject_id="subject-1",
                        operation_name="operation-1",
                        payload_json=f'{{"sequence":{sequence}}}',
                        expires_at=now + timedelta(seconds=30),
                    ),
                    max_events=3,
                )

            window = await store.load_replay_window(
                StreamResumeRequest(
                    stream_id="stream-1",
                    last_event_id="event-0",
                    subject_id="subject-1",
                    operation_name="operation-1",
                )
            )

            assert [event.sequence for event in window.events] == [1, 2]
            assert window.expired is False
        finally:
            await store.close()

    @pytest.mark.asyncio
    async def test_replay_window_when_subject_mismatch_should_expire(self) -> None:
        """验证越权恢复返回不可恢复窗口。"""

        store = MemoryStreamStateStore()
        await store.open()
        try:
            await store.append_event(
                StreamReplayEventRecord(
                    stream_id="stream-1",
                    event_id="event-0",
                    sequence=0,
                    subject_id="subject-1",
                    operation_name="operation-1",
                    payload_json="{}",
                    expires_at=datetime.now(UTC) + timedelta(seconds=30),
                ),
                max_events=3,
            )

            window = await store.load_replay_window(
                StreamResumeRequest(
                    stream_id="stream-1",
                    last_event_id="event-0",
                    subject_id="subject-2",
                    operation_name="operation-1",
                )
            )

            assert window.expired is True
            assert window.events == []
        finally:
            await store.close()

    @pytest.mark.asyncio
    async def test_append_event_when_sequence_is_not_contiguous_should_reject(self) -> None:
        """验证恢复状态存储拒绝跳号事件并完成资源回收。"""

        store = MemoryStreamStateStore()
        await store.open()
        now = datetime.now(UTC)
        try:
            await store.append_event(
                StreamReplayEventRecord(
                    stream_id="stream-1",
                    event_id="event-0",
                    sequence=0,
                    subject_id="subject-1",
                    operation_name="operation-1",
                    payload_json="{}",
                    expires_at=now + timedelta(seconds=30),
                ),
                max_events=3,
            )
            with pytest.raises(ValueError):
                await store.append_event(
                    StreamReplayEventRecord(
                        stream_id="stream-1",
                        event_id="event-2",
                        sequence=2,
                        subject_id="subject-1",
                        operation_name="operation-1",
                        payload_json="{}",
                        expires_at=now + timedelta(seconds=30),
                    ),
                    max_events=3,
                )
        finally:
            await store.close()
