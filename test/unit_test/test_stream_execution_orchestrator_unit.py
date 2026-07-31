"""流执行编排器单元测试。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Literal, cast

import pytest
from pydantic import BaseModel, ConfigDict, TypeAdapter

from src.api.testing.streaming_test_route_binder import (
    TestStreamCommand,
    TestStreamDetail,
    TestStreamItemDetail,
)
from src.application.ports.stream_event_source_port import StreamExecutionContext
from src.application.streaming.stream_execution_orchestrator import (
    StreamExecutionOrchestrator,
    StreamExecutionPolicy,
)
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.stream_contract.stream_delivery_contract import (
    StreamBatchCompletedDetail,
    StreamCollectionLimit,
)
from src.core.stream_contract.stream_event_contract import (
    StreamCompletedDetail,
    StreamEventEnvelope,
    StreamFaultDetail,
    StreamStartedDetail,
    StreamTransport,
)


class SuccessfulSource:
    """产生两个确定性业务事件的测试源。"""

    def __init__(self) -> None:
        self.closed = False

    async def open(
        self,
        *,
        command: TestStreamCommand,
        context: StreamExecutionContext,
    ) -> AsyncIterator[TestStreamDetail]:
        """产生命令指定数量的业务事件。"""

        try:
            for index in range(command.count):
                yield TestStreamItemDetail(index=index, text=f"item-{index}")
        finally:
            self.closed = True


class FailingSource:
    """首个业务事件前失败的测试源。"""

    async def open(
        self,
        *,
        command: TestStreamCommand,
        context: StreamExecutionContext,
    ) -> AsyncIterator[TestStreamDetail]:
        """抛出确定性生产异常。"""

        if command.count >= 0:
            raise RuntimeError("测试生产失败。")
        yield TestStreamItemDetail(index=0, text="unreachable")


class InvalidStreamDetail(BaseModel):
    """不属于业务事件联合的非法扩展。"""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["invalid_stream_detail"] = "invalid_stream_detail"
    schema_version: Literal["1.0"] = "1.0"


class InvalidSource:
    """产生非法业务扩展的测试源。"""

    async def open(
        self,
        *,
        command: TestStreamCommand,
        context: StreamExecutionContext,
    ) -> AsyncIterator[TestStreamDetail]:
        """产生一个不属于冻结联合的事件。"""

        yield cast(TestStreamDetail, InvalidStreamDetail())


class SlowSource:
    """可验证超时取消与生成器关闭的测试源。"""

    def __init__(self) -> None:
        self.closed = False

    async def open(
        self,
        *,
        command: TestStreamCommand,
        context: StreamExecutionContext,
    ) -> AsyncIterator[TestStreamDetail]:
        """延迟产生事件并在关闭时记录资源回收。"""

        try:
            await asyncio.sleep(1)
            yield TestStreamItemDetail(index=0, text="late")
        finally:
            self.closed = True


class TestStreamExecutionOrchestratorUnit:
    """流执行编排器单元测试集合。"""

    @pytest.mark.asyncio
    async def test_iter_events_when_source_succeeds_should_add_lifecycle_and_sequence(self) -> None:
        """验证编排器补齐开始、完成事件并生成单调序列。"""

        source = SuccessfulSource()
        events = [
            event
            async for event in self._build_orchestrator().iter_events(
                source=source,
                command=TestStreamCommand(count=2),
                context=self._build_context(StreamTransport.SSE),
            )
        ]

        assert isinstance(events[0].detail, StreamStartedDetail)
        assert isinstance(events[-1].detail, StreamCompletedDetail)
        assert [event.header.sequence for event in events] == [0, 1, 2, 3]
        assert source.closed is True

    @pytest.mark.asyncio
    async def test_iter_events_when_source_fails_should_emit_fault(self) -> None:
        """验证生产者异常应转为强类型流故障。"""

        events = [
            event
            async for event in self._build_orchestrator().iter_events(
                source=FailingSource(),
                command=TestStreamCommand(count=0),
                context=self._build_context(StreamTransport.WEBSOCKET),
            )
        ]

        assert isinstance(events[-1].detail, StreamFaultDetail)
        assert events[-1].detail.close_reason.value == "internal_error"

    @pytest.mark.asyncio
    async def test_collect_when_within_limits_should_return_same_order(self) -> None:
        """验证非流式聚合复用同一事件顺序。"""

        batch = await self._build_orchestrator().collect(
            source=SuccessfulSource(),
            command=TestStreamCommand(count=2),
            context=self._build_context(StreamTransport.HTTP),
            limit=StreamCollectionLimit(
                max_events=8,
                max_bytes=8192,
                timeout_seconds=1.0,
            ),
        )

        assert isinstance(batch.detail, StreamBatchCompletedDetail)
        assert [event.header.sequence for event in batch.detail.events] == [0, 1, 2, 3]
        assert batch.detail.event_count == 4

    @pytest.mark.asyncio
    async def test_collect_when_event_limit_exceeded_should_raise_fault(self) -> None:
        """验证聚合事件数超限应拒绝。"""

        with pytest.raises(HttpFaultException):
            await self._build_orchestrator().collect(
                source=SuccessfulSource(),
                command=TestStreamCommand(count=2),
                context=self._build_context(StreamTransport.HTTP),
                limit=StreamCollectionLimit(
                    max_events=2,
                    max_bytes=8192,
                    timeout_seconds=1.0,
                ),
            )

    @pytest.mark.asyncio
    async def test_iter_events_when_consumer_pauses_should_emit_slow_consumer_fault(self) -> None:
        """验证有界队列持续饱和时终止慢消费者。"""

        orchestrator = StreamExecutionOrchestrator(
            event_adapter=TypeAdapter(StreamEventEnvelope[TestStreamDetail]),
            policy=StreamExecutionPolicy(
                queue_capacity=1,
                send_timeout_seconds=0.01,
                max_duration_seconds=1.0,
                max_event_bytes=4096,
            ),
        )
        events = orchestrator.iter_events(
            source=SuccessfulSource(),
            command=TestStreamCommand(count=3),
            context=self._build_context(StreamTransport.SSE),
        )
        first = await anext(events)
        await asyncio.sleep(0.05)
        remaining = [event async for event in events]

        assert isinstance(first.detail, StreamStartedDetail)
        assert isinstance(remaining[-1].detail, StreamFaultDetail)
        assert remaining[-1].detail.close_reason.value == "slow_consumer"

    @pytest.mark.asyncio
    async def test_iter_events_when_detail_invalid_should_emit_protocol_fault(self) -> None:
        """验证 started 后非法业务联合被收束为协议故障。"""

        events = [
            event
            async for event in self._build_orchestrator().iter_events(
                source=InvalidSource(),
                command=TestStreamCommand(count=1),
                context=self._build_context(StreamTransport.SSE),
            )
        ]

        assert isinstance(events[-1].detail, StreamFaultDetail)
        assert events[-1].detail.error_code == "system.stream.protocol_invalid"

    @pytest.mark.asyncio
    async def test_collect_when_byte_limit_exceeded_should_close_source(self) -> None:
        """验证聚合字节超限时关闭生成器且不遗留生产任务。"""

        source = SuccessfulSource()
        with pytest.raises(HttpFaultException):
            await self._build_orchestrator().collect(
                source=source,
                command=TestStreamCommand(count=2),
                context=self._build_context(StreamTransport.HTTP),
                limit=StreamCollectionLimit(
                    max_events=8,
                    max_bytes=512,
                    timeout_seconds=1.0,
                ),
            )

        assert source.closed is True

    @pytest.mark.asyncio
    async def test_collect_when_timeout_should_close_slow_source(self) -> None:
        """验证聚合时间超限时取消并关闭慢生产者。"""

        source = SlowSource()
        with pytest.raises(HttpFaultException):
            await self._build_orchestrator().collect(
                source=source,
                command=TestStreamCommand(count=1),
                context=self._build_context(StreamTransport.HTTP),
                limit=StreamCollectionLimit(
                    max_events=8,
                    max_bytes=8192,
                    timeout_seconds=0.01,
                ),
            )

        assert source.closed is True

    def _build_orchestrator(
        self,
    ) -> StreamExecutionOrchestrator[TestStreamCommand, TestStreamDetail]:
        """构建测试编排器。"""

        return StreamExecutionOrchestrator(
            event_adapter=TypeAdapter(StreamEventEnvelope[TestStreamDetail]),
            policy=StreamExecutionPolicy(
                queue_capacity=2,
                send_timeout_seconds=0.1,
                max_duration_seconds=1.0,
                max_event_bytes=4096,
            ),
        )

    def _build_context(self, transport: StreamTransport) -> StreamExecutionContext:
        """构建测试执行上下文。"""

        return StreamExecutionContext(
            request_id="request-1",
            trace_id="trace-1",
            subject_id="subject-1",
            client_ip="127.0.0.1",
            operation_name="test_operation",
            transport=transport,
            resumable=True,
            deadline=datetime.now(UTC) + timedelta(seconds=2),
        )
