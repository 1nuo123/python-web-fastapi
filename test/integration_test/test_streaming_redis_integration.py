"""真实 Redis 流票据与恢复集成测试。"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from redis.asyncio import Redis

from src.application.streaming.stream_access_ticket_service import StreamAccessTicketService
from src.core.stream_contract.cursor_stream_contract import (
    CursorStreamAppendRequest,
    CursorStreamEvent,
    CursorStreamReadRequest,
    OpaqueStreamCursorCodec,
)
from src.core.stream_contract.stream_access_contract import (
    StreamAccessTicketIssuedDetail,
    StreamReplayEventRecord,
    StreamResumeRequest,
)
from src.infrastructure.streaming.redis_stream_state_store import RedisStreamStateStore
from test.redis_integration_support import (
    RedisIntegrationAvailability,
)

REDIS_TEST_URL_ENVIRONMENT_VARIABLE = "REDIS_TEST_URL"
REDIS_CONNECT_TIMEOUT_SECONDS = 2


class TestStreamingRedisIntegration:
    """真实 Redis 流状态集成测试集合。"""

    @pytest.mark.asyncio
    @pytest.mark.redis
    @pytest.mark.integration
    async def test_ticket_competition_should_allow_exactly_one_consumer(self) -> None:
        """验证多客户端竞争同一票据时仅一个原子消费成功。"""

        redis_resource = RedisIntegrationAvailability.create_resource(
            redis_url=os.environ[REDIS_TEST_URL_ENVIRONMENT_VARIABLE],
            timeout_seconds=REDIS_CONNECT_TIMEOUT_SECONDS,
        )
        store = self._build_store(redis_resource.async_client)
        try:
            await store.open()
            service = StreamAccessTicketService(state_store=store, ttl_seconds=30)
            ticket = await service.issue(
                subject_id="subject-1",
                operation_name="operation-1",
                client_ip="127.0.0.1",
            )
            assert isinstance(ticket.detail, StreamAccessTicketIssuedDetail)

            results = await asyncio.gather(
                *(
                    service.consume(
                        ticket=ticket.detail.ticket,
                        subject_id="subject-1",
                        operation_name="operation-1",
                        client_ip="127.0.0.1",
                    )
                    for _ in range(2)
                )
            )

            assert sorted(results) == [False, True]
        finally:
            await store.close()
            await redis_resource.close()

    @pytest.mark.asyncio
    @pytest.mark.redis
    @pytest.mark.integration
    async def test_replay_window_should_preserve_order_and_authorization(self) -> None:
        """验证 Redis 恢复窗口顺序单调且拒绝跨主体访问。"""

        redis_resource = RedisIntegrationAvailability.create_resource(
            redis_url=os.environ[REDIS_TEST_URL_ENVIRONMENT_VARIABLE],
            timeout_seconds=REDIS_CONNECT_TIMEOUT_SECONDS,
        )
        store = self._build_store(redis_resource.async_client)
        stream_id = f"stream-{uuid.uuid4()}"
        now = datetime.now(UTC)
        try:
            await store.open()
            for sequence in range(3):
                await store.append_event(
                    StreamReplayEventRecord(
                        stream_id=stream_id,
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
                    stream_id=stream_id,
                    last_event_id="event-0",
                    subject_id="subject-1",
                    operation_name="operation-1",
                )
            )
            forbidden = await store.load_replay_window(
                StreamResumeRequest(
                    stream_id=stream_id,
                    last_event_id="event-0",
                    subject_id="subject-2",
                    operation_name="operation-1",
                )
            )

            assert [event.sequence for event in window.events] == [1, 2]
            assert forbidden.expired is True
        finally:
            await store.close()
            await redis_resource.close()

    @pytest.mark.asyncio
    @pytest.mark.redis
    @pytest.mark.integration
    async def test_cursor_stream_should_trim_detect_gap_and_enforce_owner(self) -> None:
        """验证真实 Redis Streams 使用 opaque cursor、裁剪 gap 和 owner 鉴权。"""

        redis_resource = RedisIntegrationAvailability.create_resource(
            redis_url=os.environ[REDIS_TEST_URL_ENVIRONMENT_VARIABLE],
            timeout_seconds=REDIS_CONNECT_TIMEOUT_SECONDS,
        )
        store = self._build_store(redis_resource.async_client)
        stream_key = f"cursor-{uuid.uuid4()}"
        owner = "subject-1"
        now = datetime.now(UTC)
        try:
            await store.open()
            first_cursor: str | None = None
            for index in range(3):
                appended = await store.append_cursor_event(
                    CursorStreamAppendRequest(
                        event=CursorStreamEvent(
                            stream_key=stream_key,
                            owner_subject_id=owner,
                            event_id=uuid.uuid4(),
                            payload=f"event-{index}".encode(),
                            expires_at=now + timedelta(seconds=30),
                        ),
                        max_events=2,
                    )
                )
                if index == 0:
                    first_cursor = appended.cursor
            assert first_cursor is not None

            gap = await store.read_cursor_window(
                CursorStreamReadRequest(
                    stream_key=stream_key,
                    owner_subject_id=owner,
                    after_cursor=first_cursor,
                )
            )
            window = await store.read_cursor_window(
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
                    after_cursor=window.next_cursor,
                )
            )

            assert gap.gap is True
            assert gap.snapshot_required is True
            assert len(window.events) == 1
            assert len(following.events) == 1
            assert following.next_cursor is not None
            with pytest.raises(PermissionError, match="owner"):
                await store.read_cursor_window(
                    CursorStreamReadRequest(
                        stream_key=stream_key,
                        owner_subject_id="subject-2",
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

            missing = await store.read_cursor_window(
                CursorStreamReadRequest(
                    stream_key=f"missing-{uuid.uuid4()}",
                    owner_subject_id=owner,
                )
            )
            assert missing.events == ()
            assert await store.purge_expired() == 0
            assert store._stream_id_before("1-0", "2-0") is True  # noqa: SLF001
            assert store._stream_id_before("2-0", "1-0") is False  # noqa: SLF001
        finally:
            await store.close()
            await redis_resource.close()

    def _build_store(self, client: Redis) -> RedisStreamStateStore:
        """按测试环境变量构建隔离 Redis 状态存储。"""

        return RedisStreamStateStore(
            client=client,
            key_prefix=f"stream-test-{uuid.uuid4()}",
        )
