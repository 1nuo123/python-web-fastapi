"""真实 Redis 流票据与恢复集成测试。"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from src.application.streaming.stream_access_ticket_service import StreamAccessTicketService
from src.core.stream_contract.stream_access_contract import (
    StreamReplayEventRecord,
    StreamResumeRequest,
)
from src.infrastructure.streaming.redis_stream_state_store import RedisStreamStateStore

REDIS_TEST_URL_ENVIRONMENT_VARIABLE = "REDIS_TEST_URL"


class TestStreamingRedisIntegration:
    """真实 Redis 流状态集成测试集合。"""

    @pytest.mark.asyncio
    @pytest.mark.redis
    @pytest.mark.integration
    async def test_ticket_competition_should_allow_exactly_one_consumer(self) -> None:
        """验证多客户端竞争同一票据时仅一个原子消费成功。"""

        store = self._build_store()
        await store.open()
        try:
            service = StreamAccessTicketService(state_store=store, ttl_seconds=30)
            ticket = await service.issue(
                subject_id="subject-1",
                operation_name="operation-1",
                client_ip="127.0.0.1",
            )

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

    @pytest.mark.asyncio
    @pytest.mark.redis
    @pytest.mark.integration
    async def test_replay_window_should_preserve_order_and_authorization(self) -> None:
        """验证 Redis 恢复窗口顺序单调且拒绝跨主体访问。"""

        store = self._build_store()
        await store.open()
        stream_id = f"stream-{uuid.uuid4()}"
        now = datetime.now(UTC)
        try:
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

    def _build_store(self) -> RedisStreamStateStore:
        """按测试环境变量构建隔离 Redis 状态存储。"""

        redis_url = os.environ[REDIS_TEST_URL_ENVIRONMENT_VARIABLE]
        return RedisStreamStateStore(
            redis_url=redis_url,
            key_prefix=f"stream-test-{uuid.uuid4()}",
            socket_connect_timeout_seconds=2.0,
            max_connections=4,
        )
