"""流状态存储与票据服务单元测试。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from src.application.streaming.stream_access_ticket_service import StreamAccessTicketService
from src.core.stream_contract.cursor_stream_contract import (
    CursorStreamAppendRequest,
    CursorStreamEvent,
    CursorStreamReadRequest,
    OpaqueStreamCursorCodec,
)
from src.core.stream_contract.stream_access_contract import (
    StreamAccessTicketIssuedDetail,
    StreamAccessTicketRecord,
    StreamReplayEventRecord,
    StreamResumeRequest,
    StreamTicketConsumptionRequest,
    StreamTicketLookupRequest,
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
            assert isinstance(ticket.detail, StreamAccessTicketIssuedDetail)

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

    @pytest.mark.asyncio
    async def test_ticket_record_should_enforce_expiry_operation_and_client_binding(self) -> None:
        """验证可信票据记录按过期时间、操作和客户端地址原子消费。"""

        store = MemoryStreamStateStore()
        with pytest.raises(RuntimeError, match="尚未打开"):
            await store.purge_expired()
        await store.open()
        now = datetime.now(UTC)
        try:
            records = (
                StreamAccessTicketRecord(
                    ticket_digest="expired",
                    subject_id="subject-1",
                    operation_name="operation-1",
                    client_ip="127.0.0.1",
                    expires_at=now - timedelta(seconds=1),
                ),
                StreamAccessTicketRecord(
                    ticket_digest="bound",
                    subject_id="subject-1",
                    operation_name="operation-1",
                    client_ip="127.0.0.1",
                    expires_at=now + timedelta(seconds=30),
                ),
                StreamAccessTicketRecord(
                    ticket_digest="lookup",
                    subject_id="subject-2",
                    operation_name="operation-2",
                    client_ip=None,
                    expires_at=now + timedelta(seconds=30),
                ),
            )
            for record in records:
                await store.store_ticket(record)

            assert not await store.consume_ticket(
                StreamTicketConsumptionRequest(
                    ticket_digest="missing",
                    subject_id="subject-1",
                    operation_name="operation-1",
                    client_ip="127.0.0.1",
                    consumed_at=now,
                )
            )
            assert not await store.consume_ticket(
                StreamTicketConsumptionRequest(
                    ticket_digest="expired",
                    subject_id="subject-1",
                    operation_name="operation-1",
                    client_ip="127.0.0.1",
                    consumed_at=now,
                )
            )
            for subject_id, operation_name, client_ip in (
                ("subject-2", "operation-1", "127.0.0.1"),
                ("subject-1", "operation-2", "127.0.0.1"),
                ("subject-1", "operation-1", "127.0.0.2"),
            ):
                assert not await store.consume_ticket(
                    StreamTicketConsumptionRequest(
                        ticket_digest="bound",
                        subject_id=subject_id,
                        operation_name=operation_name,
                        client_ip=client_ip,
                        consumed_at=now,
                    )
                )

            assert (
                await store.consume_ticket_record(
                    StreamTicketLookupRequest(
                        ticket_digest="missing",
                        operation_name="operation-2",
                        client_ip=None,
                        consumed_at=now,
                    )
                )
                is None
            )
            assert (
                await store.consume_ticket_record(
                    StreamTicketLookupRequest(
                        ticket_digest="lookup",
                        operation_name="wrong",
                        client_ip=None,
                        consumed_at=now,
                    )
                )
                is None
            )
            consumed = await store.consume_ticket_record(
                StreamTicketLookupRequest(
                    ticket_digest="lookup",
                    operation_name="operation-2",
                    client_ip=None,
                    consumed_at=now,
                )
            )
            assert consumed is not None
            assert consumed.subject_id == "subject-2"
            assert await store.purge_expired() == 0
        finally:
            await store.close()

    @pytest.mark.asyncio
    async def test_purge_and_replay_should_remove_expired_and_reject_identity_change(self) -> None:
        """验证重放状态清理、空窗口和同流身份不可变。"""

        store = MemoryStreamStateStore(opened=True)
        now = datetime.now(UTC)
        try:
            await store.store_ticket(
                StreamAccessTicketRecord(
                    ticket_digest="expired",
                    subject_id="subject-1",
                    operation_name="operation-1",
                    client_ip=None,
                    expires_at=now - timedelta(seconds=1),
                )
            )
            await store.append_event(
                StreamReplayEventRecord(
                    stream_id="expired-stream",
                    event_id="expired-event",
                    sequence=0,
                    subject_id="subject-1",
                    operation_name="operation-1",
                    payload_json="{}",
                    expires_at=now - timedelta(seconds=1),
                ),
                max_events=2,
            )
            assert await store.purge_expired() == 2

            empty = await store.load_replay_window(
                StreamResumeRequest(
                    stream_id="missing",
                    last_event_id="missing",
                    subject_id="subject-1",
                    operation_name="operation-1",
                )
            )
            assert empty.expired is True

            await store.append_event(
                StreamReplayEventRecord(
                    stream_id="identity-stream",
                    event_id="event-0",
                    sequence=0,
                    subject_id="subject-1",
                    operation_name="operation-1",
                    payload_json="{}",
                    expires_at=now + timedelta(seconds=30),
                ),
                max_events=2,
            )
            with pytest.raises(ValueError, match="主体"):
                await store.append_event(
                    StreamReplayEventRecord(
                        stream_id="identity-stream",
                        event_id="event-1",
                        sequence=1,
                        subject_id="subject-2",
                        operation_name="operation-1",
                        payload_json="{}",
                        expires_at=now + timedelta(seconds=30),
                    ),
                    max_events=2,
                )
            missing_cursor = await store.load_replay_window(
                StreamResumeRequest(
                    stream_id="identity-stream",
                    last_event_id="missing",
                    subject_id="subject-1",
                    operation_name="operation-1",
                )
            )
            assert missing_cursor.expired is True
        finally:
            await store.close()

    @pytest.mark.asyncio
    async def test_cursor_stream_should_read_trim_gap_expiry_and_owner_boundaries(self) -> None:
        """验证 v2 opaque cursor 的读取、裁剪 gap 和 owner 隔离。"""

        store = MemoryStreamStateStore(opened=True)
        stream_key = "cursor-stream"
        owner = "subject-1"
        now = datetime.now(UTC)
        try:
            first_cursor: str | None = None
            for index in range(3):
                result = await store.append_cursor_event(
                    CursorStreamAppendRequest(
                        event=CursorStreamEvent(
                            stream_key=stream_key,
                            owner_subject_id=owner,
                            event_id=uuid4(),
                            payload=f"event-{index}".encode(),
                            expires_at=now + timedelta(seconds=30),
                        ),
                        max_events=2,
                    )
                )
                if index == 0:
                    first_cursor = result.cursor
            assert first_cursor is not None

            gap = await store.read_cursor_window(
                CursorStreamReadRequest(
                    stream_key=stream_key,
                    owner_subject_id=owner,
                    after_cursor=first_cursor,
                )
            )
            current = await store.read_cursor_window(
                CursorStreamReadRequest(
                    stream_key=stream_key,
                    owner_subject_id=owner,
                    limit=1,
                )
            )
            following = await store.read_cursor_window(
                CursorStreamReadRequest(
                    stream_key=stream_key,
                    owner_subject_id=owner,
                    after_cursor=current.next_cursor,
                )
            )

            assert gap.gap is True
            assert gap.snapshot_required is True
            assert len(current.events) == 1
            assert len(following.events) == 1
            assert following.next_cursor is not None
            with pytest.raises(PermissionError, match="owner"):
                await store.read_cursor_window(
                    CursorStreamReadRequest(
                        stream_key=stream_key,
                        owner_subject_id="subject-2",
                    )
                )
            with pytest.raises(PermissionError, match="owner"):
                await store.append_cursor_event(
                    CursorStreamAppendRequest(
                        event=CursorStreamEvent(
                            stream_key=stream_key,
                            owner_subject_id="subject-2",
                            event_id=uuid4(),
                            payload=b"forbidden",
                            expires_at=now + timedelta(seconds=30),
                        ),
                        max_events=2,
                    )
                )
            with pytest.raises(ValueError, match="结构"):
                await store.read_cursor_window(
                    CursorStreamReadRequest(
                        stream_key=stream_key,
                        owner_subject_id=owner,
                        after_cursor=OpaqueStreamCursorCodec.encode("invalid"),
                    )
                )

            empty = await store.read_cursor_window(
                CursorStreamReadRequest(
                    stream_key="missing",
                    owner_subject_id=owner,
                )
            )
            assert empty.events == ()

            await store.append_cursor_event(
                CursorStreamAppendRequest(
                    event=CursorStreamEvent(
                        stream_key="expired-cursor",
                        owner_subject_id=owner,
                        event_id=uuid4(),
                        payload=b"expired",
                        expires_at=now - timedelta(seconds=1),
                    ),
                    max_events=2,
                )
            )
            expired = await store.read_cursor_window(
                CursorStreamReadRequest(
                    stream_key="expired-cursor",
                    owner_subject_id=owner,
                )
            )
            assert expired.events == ()
        finally:
            await store.close()
