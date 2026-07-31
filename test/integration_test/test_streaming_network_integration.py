"""真实 Uvicorn 网络流式集成测试。"""

from __future__ import annotations

import asyncio
import json
import socket
from time import perf_counter

import httpx
import pytest
import uvicorn
from sse_starlette.sse import AppStatus
from websockets.asyncio.client import connect

from src.api.testing.streaming_test_route_binder import (
    TEST_STREAM_BEARER_TOKEN,
    TEST_STREAM_COMMAND_KIND,
    TEST_STREAM_SSE_PATH,
    TEST_STREAM_TICKET_PATH,
    TEST_STREAM_WEBSOCKET_PATH,
)
from src.api.testing.test_app_factory import TestAppFactory

SERVER_START_TIMEOUT_SECONDS = 10.0
MINIMUM_NATIVE_EVENT_SOURCE_DATA_LINES = 2


class TestStreamingNetworkIntegration:
    """真实网络 SSE 与 WebSocket 集成测试集合。"""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_real_network_should_stream_incrementally_and_support_websocket(self) -> None:
        """验证真实端口上 SSE 增量到达与 WebSocket 双向订阅。"""

        server, server_task, listener, port = await self._start_server()
        try:
            timestamps = await self._read_sse_timestamps(port)
            native_data_line_count = await self._read_native_event_source(port)
            websocket_item = await self._read_websocket_item(port)

            assert len(timestamps) >= 3
            assert timestamps[-1] - timestamps[0] >= 0.05
            assert native_data_line_count >= MINIMUM_NATIVE_EVENT_SOURCE_DATA_LINES
            assert websocket_item["detail"]["kind"] == "test_stream_item"
        finally:
            server.should_exit = True
            try:
                await asyncio.wait_for(server_task, timeout=SERVER_START_TIMEOUT_SECONDS)
            finally:
                listener.close()
                AppStatus.should_exit = False

    async def _start_server(
        self,
    ) -> tuple[uvicorn.Server, asyncio.Task[None], socket.socket, int]:
        """启动绑定随机环回端口的真实 Uvicorn 服务。"""

        app = TestAppFactory().create()
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = int(listener.getsockname()[1])
        server = uvicorn.Server(
            uvicorn.Config(
                app,
                host="127.0.0.1",
                port=port,
                log_level="warning",
                lifespan="on",
            )
        )
        server_task = asyncio.create_task(server.serve(sockets=[listener]))
        started_at = perf_counter()
        while not server.started:
            if perf_counter() - started_at > SERVER_START_TIMEOUT_SECONDS:
                server.should_exit = True
                try:
                    await server_task
                finally:
                    listener.close()
                    AppStatus.should_exit = False
                raise TimeoutError("Uvicorn 测试服务启动超时。")
            await asyncio.sleep(0.01)
        return server, server_task, listener, port

    async def _read_sse_timestamps(self, port: int) -> list[float]:
        """读取真实 SSE 数据行到达时间。"""

        timestamps: list[float] = []
        async with httpx.AsyncClient(timeout=5.0) as client:
            async with client.stream(
                "POST",
                f"http://127.0.0.1:{port}{TEST_STREAM_SSE_PATH}",
                json={
                    "kind": TEST_STREAM_COMMAND_KIND,
                    "schema_version": "1.0",
                    "count": 2,
                    "delay_milliseconds": 100,
                },
            ) as response:
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        timestamps.append(perf_counter())
        return timestamps

    async def _read_native_event_source(self, port: int) -> int:
        """通过真实 GET SSE 连接消费短期单次票据。

        :param port: Uvicorn 随机环回端口。
        :type port: int
        :returns: 收到的 SSE 数据行数量。
        :rtype: int
        """

        base_url = f"http://127.0.0.1:{port}"
        async with httpx.AsyncClient(timeout=5.0) as client:
            ticket_payload = (await client.post(base_url + TEST_STREAM_TICKET_PATH)).json()
            command_json = json.dumps(
                {
                    "kind": TEST_STREAM_COMMAND_KIND,
                    "schema_version": "1.0",
                    "count": 0,
                    "delay_milliseconds": 0,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
            data_line_count = 0
            async with client.stream(
                "GET",
                base_url + TEST_STREAM_SSE_PATH,
                params={
                    "ticket": ticket_payload["detail"]["ticket"],
                    "subject_id": ticket_payload["header"]["subject_id"],
                    "command": command_json,
                },
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data_line_count += 1
            return data_line_count

    async def _read_websocket_item(self, port: int) -> dict[str, object]:
        """通过真实 WebSocket 客户端读取业务事件。"""

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
                                "count": 1,
                                "delay_milliseconds": 0,
                            },
                        },
                    }
                )
            )
            await websocket.recv()
            payload = await websocket.recv()
        parsed = json.loads(str(payload))
        if not isinstance(parsed, dict):
            raise TypeError("WebSocket 测试事件必须是 JSON 对象。")
        return parsed
