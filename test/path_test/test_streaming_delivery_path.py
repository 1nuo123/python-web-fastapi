"""统一流式三种交付路径测试。"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from src.api.testing.streaming_test_route_binder import (
    TEST_STREAM_BATCH_PATH,
    TEST_STREAM_BEARER_TOKEN,
    TEST_STREAM_COMMAND_KIND,
    TEST_STREAM_SSE_PATH,
    TEST_STREAM_WEBSOCKET_PATH,
)
from src.api.testing.test_app_factory import TestAppFactory


class TestStreamingDeliveryPath:
    """统一流式交付路径测试集合。"""

    def test_three_transports_should_share_business_event_content(self) -> None:
        """验证非流式、SSE、WebSocket 复用同一事件源语义。"""

        command = self._build_command()
        with TestClient(TestAppFactory().create()) as client:
            batch_response = client.post(TEST_STREAM_BATCH_PATH, json=command)
            batch_item = next(
                event
                for event in batch_response.json()["data"]["detail"]["events"]
                if event["detail"]["kind"] == "test_stream_item"
            )
            with client.stream("POST", TEST_STREAM_SSE_PATH, json=command) as sse_response:
                sse_payloads = [
                    json.loads(line.removeprefix("data: "))
                    for line in sse_response.iter_lines()
                    if line.startswith("data: ")
                ]
            sse_item = next(
                event for event in sse_payloads if event["detail"]["kind"] == "test_stream_item"
            )
            with client.websocket_connect(
                TEST_STREAM_WEBSOCKET_PATH,
                headers={
                    "origin": "http://testserver",
                    "authorization": f"Bearer {TEST_STREAM_BEARER_TOKEN}",
                },
            ) as websocket:
                websocket.send_json(self._build_subscribe())
                websocket_payloads = [json.loads(websocket.receive_text()) for _ in range(3)]
            websocket_item = next(
                event
                for event in websocket_payloads
                if event["detail"]["kind"] == "test_stream_item"
            )

        assert batch_item["detail"] == sse_item["detail"] == websocket_item["detail"]

    def test_three_transports_when_source_fails_should_share_fault_code(self) -> None:
        """验证同一事件源故障在非流式、SSE 与 WebSocket 中保持错误码一致。"""

        command = self._build_command()
        command["fail_after_events"] = 0
        with TestClient(TestAppFactory().create()) as client:
            batch_response = client.post(TEST_STREAM_BATCH_PATH, json=command)
            with client.stream("POST", TEST_STREAM_SSE_PATH, json=command) as response:
                sse_events = [
                    json.loads(line.removeprefix("data: "))
                    for line in response.iter_lines()
                    if line.startswith("data: ")
                ]
            with client.websocket_connect(
                TEST_STREAM_WEBSOCKET_PATH,
                headers={
                    "origin": "http://testserver",
                    "authorization": f"Bearer {TEST_STREAM_BEARER_TOKEN}",
                },
            ) as websocket:
                websocket.send_json(
                    {
                        "header": {
                            "kind": "stream_client_control_header",
                            "schema_version": "1.0",
                            "control_kind": "subscribe",
                        },
                        "detail": {
                            "kind": "subscribe",
                            "schema_version": "1.0",
                            "command": command,
                        },
                    }
                )
                websocket_events = [json.loads(websocket.receive_text()) for _ in range(2)]

        batch_code = batch_response.json()["header"]["code"]
        sse_code = sse_events[-1]["detail"]["error_code"]
        websocket_code = websocket_events[-1]["detail"]["error_code"]
        assert batch_code == sse_code == websocket_code == "system.internal.unexpected"

    def _build_command(self) -> dict[str, object]:
        """构建单事件测试命令。"""

        return {
            "kind": TEST_STREAM_COMMAND_KIND,
            "schema_version": "1.0",
            "count": 1,
            "delay_milliseconds": 0,
        }

    def _build_subscribe(self) -> dict[str, object]:
        """构建单事件订阅控制帧。"""

        return {
            "header": {
                "kind": "stream_client_control_header",
                "schema_version": "1.0",
                "control_kind": "subscribe",
            },
            "detail": {
                "kind": "subscribe",
                "schema_version": "1.0",
                "command": self._build_command(),
            },
        }
