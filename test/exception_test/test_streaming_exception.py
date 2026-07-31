"""统一流式异常测试。"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from src.api.testing.streaming_test_route_binder import (
    TEST_STREAM_BEARER_TOKEN,
    TEST_STREAM_COMMAND_KIND,
    TEST_STREAM_WEBSOCKET_PATH,
)
from src.api.testing.test_app_factory import TestAppFactory


class TestStreamingException:
    """统一流式异常测试集合。"""

    def test_websocket_when_origin_invalid_should_reject_before_accept(self) -> None:
        """验证非法 Origin 在建连前拒绝。"""

        with TestClient(TestAppFactory().create()) as client:
            with pytest.raises(WebSocketDisconnect):
                with client.websocket_connect(
                    TEST_STREAM_WEBSOCKET_PATH,
                    headers={
                        "origin": "https://evil.example.com",
                        "authorization": f"Bearer {TEST_STREAM_BEARER_TOKEN}",
                    },
                ):
                    pass

    def test_websocket_when_bearer_invalid_should_reject_before_accept(self) -> None:
        """验证非法 Bearer 在建连前拒绝。"""

        with TestClient(TestAppFactory().create()) as client:
            with pytest.raises(WebSocketDisconnect):
                with client.websocket_connect(
                    TEST_STREAM_WEBSOCKET_PATH,
                    headers={
                        "origin": "http://testserver",
                        "authorization": "Bearer invalid",
                    },
                ):
                    pass

    def test_websocket_when_control_has_extra_field_should_close_policy(self) -> None:
        """验证控制扩展包含额外字段时按策略关闭。"""

        with TestClient(TestAppFactory().create()) as client:
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
                            "command": {
                                "kind": TEST_STREAM_COMMAND_KIND,
                                "schema_version": "1.0",
                                "count": 1,
                                "delay_milliseconds": 0,
                            },
                            "extra": True,
                        },
                    }
                )
                fault = json.loads(websocket.receive_text())
                with pytest.raises(WebSocketDisconnect) as captured:
                    websocket.receive_text()

        assert fault["detail"]["kind"] == "stream_fault"
        assert captured.value.code == 1008

    def test_websocket_when_binary_subscribe_should_close_policy(self) -> None:
        """验证二进制首次控制帧被协议拒绝。"""

        with TestClient(TestAppFactory().create()) as client:
            with client.websocket_connect(
                TEST_STREAM_WEBSOCKET_PATH,
                headers={
                    "origin": "http://testserver",
                    "authorization": f"Bearer {TEST_STREAM_BEARER_TOKEN}",
                },
            ) as websocket:
                websocket.send_bytes(b"binary")
                fault = json.loads(websocket.receive_text())
                with pytest.raises(WebSocketDisconnect) as captured:
                    websocket.receive_text()

        assert fault["detail"]["kind"] == "stream_fault"
        assert captured.value.code == 1008
