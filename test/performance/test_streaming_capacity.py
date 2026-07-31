"""统一流式受控容量与资源回收测试。"""

from __future__ import annotations

import asyncio
import gc
import json
import os
from datetime import UTC, datetime, timedelta

import httpx
import psutil
import pytest
from pydantic import TypeAdapter
from websockets.asyncio.client import connect

from src.api.testing.streaming_test_route_binder import (
    TEST_STREAM_BEARER_TOKEN,
    TEST_STREAM_COMMAND_KIND,
    TEST_STREAM_SSE_PATH,
    TEST_STREAM_WEBSOCKET_PATH,
    TestStreamCommand,
    TestStreamDetail,
    TestStreamEventSource,
)
from src.application.ports.stream_event_source_port import StreamExecutionContext
from src.application.streaming.stream_execution_orchestrator import (
    StreamExecutionOrchestrator,
    StreamExecutionPolicy,
)
from src.core.stream_contract.stream_event_contract import StreamEventEnvelope, StreamTransport
from test.performance.streaming_network_harness import StreamingNetworkServerFactory

CONCURRENT_STREAM_COUNT = 16
EVENTS_PER_STREAM = 8
MAX_TASK_GROWTH = 4
REAL_NETWORK_CONNECTIONS_PER_TRANSPORT = 4
REAL_NETWORK_REPEAT_COUNT = 3
REAL_NETWORK_WARMUP_CONNECTIONS_PER_TRANSPORT = 1
MAXIMUM_RSS_GROWTH_BYTES = 12 * 1024 * 1024


class TestStreamingCapacity:
    """统一流式受控容量测试集合。"""

    @pytest.mark.asyncio
    @pytest.mark.performance
    async def test_concurrent_streams_after_completion_should_release_tasks(self) -> None:
        """验证并发流完成与 GC 后任务数回落到允许区间。"""

        baseline_tasks = len(asyncio.all_tasks())
        orchestrator = StreamExecutionOrchestrator(
            event_adapter=TypeAdapter(StreamEventEnvelope[TestStreamDetail]),
            policy=StreamExecutionPolicy(
                queue_capacity=4,
                send_timeout_seconds=0.5,
                max_duration_seconds=5.0,
                max_event_bytes=16384,
            ),
        )

        async def consume(index: int) -> int:
            context = StreamExecutionContext(
                request_id=f"request-{index}",
                trace_id=None,
                subject_id=f"subject-{index}",
                client_ip="127.0.0.1",
                operation_name="capacity_test",
                transport=StreamTransport.SSE,
                resumable=False,
                deadline=datetime.now(UTC) + timedelta(seconds=5),
            )
            return sum(
                1
                for _ in [
                    event
                    async for event in orchestrator.iter_events(
                        source=TestStreamEventSource(),
                        command=TestStreamCommand(count=EVENTS_PER_STREAM),
                        context=context,
                    )
                ]
            )

        counts = await asyncio.gather(*(consume(index) for index in range(CONCURRENT_STREAM_COUNT)))
        gc.collect()
        await asyncio.sleep(0)

        assert all(count == EVENTS_PER_STREAM + 2 for count in counts)
        assert len(asyncio.all_tasks()) <= baseline_tasks + MAX_TASK_GROWTH

    @pytest.mark.asyncio
    @pytest.mark.performance
    async def test_real_sse_and_websocket_reconnects_should_return_resources_to_baseline(
        self,
    ) -> None:
        """验证真实并发 SSE/WS 反复连接后任务与 RSS 回落到冻结阈值。"""

        process = psutil.Process(os.getpid())
        network_server = await StreamingNetworkServerFactory().create()
        try:
            await asyncio.gather(
                *(
                    self._consume_real_sse(network_server.port)
                    for _index in range(REAL_NETWORK_WARMUP_CONNECTIONS_PER_TRANSPORT)
                ),
                *(
                    self._consume_real_websocket(network_server.port)
                    for _index in range(REAL_NETWORK_WARMUP_CONNECTIONS_PER_TRANSPORT)
                ),
            )
            gc.collect()
            await asyncio.sleep(0)
            baseline_rss = process.memory_info().rss
            baseline_tasks = len(asyncio.all_tasks())
            for _repeat_index in range(REAL_NETWORK_REPEAT_COUNT):
                await asyncio.gather(
                    *(
                        self._consume_real_sse(network_server.port)
                        for _index in range(REAL_NETWORK_CONNECTIONS_PER_TRANSPORT)
                    ),
                    *(
                        self._consume_real_websocket(network_server.port)
                        for _index in range(REAL_NETWORK_CONNECTIONS_PER_TRANSPORT)
                    ),
                )
        finally:
            await network_server.close()
        gc.collect()
        await asyncio.sleep(0)

        assert len(asyncio.all_tasks()) <= baseline_tasks + MAX_TASK_GROWTH
        assert process.memory_info().rss <= baseline_rss + MAXIMUM_RSS_GROWTH_BYTES

    async def _consume_real_sse(self, port: int) -> None:
        """完整消费一次真实 SSE 连接并关闭 HTTP 客户端。"""

        async with httpx.AsyncClient(timeout=5.0) as client:
            async with client.stream(
                "POST",
                f"http://127.0.0.1:{port}{TEST_STREAM_SSE_PATH}",
                json={
                    "kind": TEST_STREAM_COMMAND_KIND,
                    "schema_version": "1.0",
                    "count": 2,
                    "delay_milliseconds": 10,
                },
            ) as response:
                response.raise_for_status()
                async for _line in response.aiter_lines():
                    pass

    async def _consume_real_websocket(self, port: int) -> None:
        """完整消费一次真实 WebSocket 连接并关闭客户端。"""

        uri = f"ws://127.0.0.1:{port}{TEST_STREAM_WEBSOCKET_PATH}"
        async with connect(
            uri,
            origin="http://testserver",
            additional_headers={"Authorization": f"Bearer {TEST_STREAM_BEARER_TOKEN}"},
        ) as websocket:
            await websocket.send(
                json.dumps(
                    {
                        "header": {
                            "kind": "stream_client_control_header",
                            "schema_version": "1.0",
                            "control_kind": "subscribe",
                        },
                        "detail": {
                            "kind": "subscribe",
                            "schema_version": "1.0",
                            "command": {
                                "kind": TEST_STREAM_COMMAND_KIND,
                                "schema_version": "1.0",
                                "count": 2,
                                "delay_milliseconds": 10,
                            },
                        },
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
            for _event_index in range(4):
                await websocket.recv()
