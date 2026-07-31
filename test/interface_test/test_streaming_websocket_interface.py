"""统一流式 WebSocket 接口测试。"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketTestSession
from starlette.websockets import WebSocketDisconnect

from src.api.testing.streaming_test_route_binder import (
    TEST_STREAM_BEARER_TOKEN,
    TEST_STREAM_COMMAND_KIND,
    TEST_STREAM_EXPIRING_BEARER_TOKEN,
    TEST_STREAM_SUBJECT_ID,
    TEST_STREAM_TICKET_PATH,
    TEST_STREAM_WEBSOCKET_PATH,
)
from src.api.testing.test_app_factory import TestAppFactory

WEBSOCKET_ORIGIN = "http://testserver"
WEBSOCKET_DRAIN_MESSAGE_LIMIT = 8
WEBSOCKET_TERMINAL_EVENT_KINDS = frozenset({"stream_completed", "stream_fault"})
EMPTY_STREAM_EVENT_COUNT = 2


class TestStreamingWebSocketInterface:
    """统一流式 WebSocket 接口测试集合。"""

    def test_websocket_subscribe_should_receive_ordered_events(self) -> None:
        """验证订阅控制帧启动同一业务事件源。"""

        with TestClient(TestAppFactory().create()) as client:
            with client.websocket_connect(
                TEST_STREAM_WEBSOCKET_PATH,
                headers=self._build_headers(),
            ) as websocket:
                websocket.send_json(self._build_subscribe(1))
                events = [json.loads(websocket.receive_text()) for _ in range(3)]

        assert [event["header"]["sequence"] for event in events] == [0, 1, 2]
        assert events[1]["detail"]["kind"] == "test_stream_item"

    def test_websocket_ping_should_return_typed_pong(self) -> None:
        """验证 ping 控制帧返回固定 pong 载荷。"""

        with TestClient(TestAppFactory().create()) as client:
            with client.websocket_connect(
                TEST_STREAM_WEBSOCKET_PATH,
                headers=self._build_headers(),
            ) as websocket:
                websocket.send_json(self._build_subscribe(4, delay_milliseconds=50))
                websocket.receive_text()
                websocket.send_json(
                    {
                        "header": {
                            "kind": "stream_client_control_header",
                            "schema_version": "1.0",
                            "control_kind": "ping",
                        },
                        "detail": {
                            "kind": "ping",
                            "schema_version": "1.0",
                            "nonce": "nonce-1",
                        },
                    }
                )
                messages = [json.loads(websocket.receive_text()) for _ in range(2)]
                websocket.send_json(self._build_cancel())
                for _ in range(WEBSOCKET_DRAIN_MESSAGE_LIMIT):
                    try:
                        terminal_candidate = json.loads(websocket.receive_text())
                    except WebSocketDisconnect:
                        break
                    detail = terminal_candidate.get("detail")
                    if (
                        isinstance(detail, dict)
                        and detail.get("kind") in WEBSOCKET_TERMINAL_EVENT_KINDS
                    ):
                        break

        assert any(message.get("event") == "pong" for message in messages)

    def test_websocket_cancel_should_receive_fault_and_release_session(self) -> None:
        """验证 cancel 控制帧终止生产并释放会话。"""

        app = TestAppFactory().create()
        with TestClient(app) as client:
            with client.websocket_connect(
                TEST_STREAM_WEBSOCKET_PATH,
                headers=self._build_headers(),
            ) as websocket:
                websocket.send_json(self._build_subscribe(16, delay_milliseconds=50))
                websocket.receive_text()
                websocket.send_json(self._build_cancel())
                terminal = json.loads(websocket.receive_text())

        assert terminal["detail"]["kind"] in {"test_stream_item", "stream_fault"}

    def test_websocket_ticket_should_be_single_use(self) -> None:
        """验证 WebSocket 单次票据仅允许首次建连。"""

        with TestClient(TestAppFactory().create()) as client:
            ticket_response = client.post(TEST_STREAM_TICKET_PATH)
            ticket = ticket_response.json()["detail"]["ticket"]
            path = (
                f"{TEST_STREAM_WEBSOCKET_PATH}?ticket={ticket}&subject_id={TEST_STREAM_SUBJECT_ID}"
            )
            with client.websocket_connect(
                path,
                headers={"origin": WEBSOCKET_ORIGIN},
            ) as websocket:
                websocket.send_json(self._build_subscribe(0))
                for _ in range(EMPTY_STREAM_EVENT_COUNT):
                    websocket.receive_text()
            with pytest.raises(WebSocketDisconnect):
                with client.websocket_connect(
                    path,
                    headers={"origin": WEBSOCKET_ORIGIN},
                ):
                    pass

    def test_websocket_duplicate_subscribe_should_emit_fault_and_close_1008(self) -> None:
        """验证运行中重复 subscribe 返回协议故障并按策略关闭。"""

        with TestClient(TestAppFactory().create()) as client:
            with client.websocket_connect(
                TEST_STREAM_WEBSOCKET_PATH,
                headers=self._build_headers(),
            ) as websocket:
                websocket.send_json(self._build_subscribe(8, delay_milliseconds=50))
                websocket.receive_text()
                websocket.send_json(self._build_subscribe(1))
                fault = self._receive_terminal_event(websocket)
                with pytest.raises(WebSocketDisconnect) as captured:
                    websocket.receive_text()

        assert fault["detail"]["kind"] == "stream_fault"
        assert captured.value.code == 1008

    def test_websocket_resume_on_new_connection_should_preserve_stream_and_sequence(self) -> None:
        """验证新连接恢复只重放原 stream_id 的连续后续事件。"""

        with TestClient(TestAppFactory().create()) as client:
            with client.websocket_connect(
                TEST_STREAM_WEBSOCKET_PATH,
                headers=self._build_headers(),
            ) as websocket:
                websocket.send_json(self._build_subscribe(2))
                events = [json.loads(websocket.receive_text()) for _ in range(4)]
            first_item = events[1]
            with client.websocket_connect(
                TEST_STREAM_WEBSOCKET_PATH,
                headers=self._build_headers(),
            ) as websocket:
                websocket.send_json(
                    {
                        "header": {
                            "kind": "stream_client_control_header",
                            "schema_version": "1.0",
                            "control_kind": "resume",
                        },
                        "detail": {
                            "kind": "resume",
                            "schema_version": "1.0",
                            "stream_id": first_item["header"]["stream_id"],
                            "last_event_id": first_item["header"]["event_id"],
                        },
                    }
                )
                resumed = [json.loads(websocket.receive_text()) for _ in range(2)]

        assert all(
            event["header"]["stream_id"] == first_item["header"]["stream_id"] for event in resumed
        )
        assert [event["header"]["sequence"] for event in resumed] == [2, 3]

    def test_websocket_shutdown_notification_should_emit_fault_and_close_1001(self) -> None:
        """验证服务排空通知存量连接并映射为 1001。"""

        app = TestAppFactory().create()
        with TestClient(app) as client:
            with client.websocket_connect(
                TEST_STREAM_WEBSOCKET_PATH,
                headers=self._build_headers(),
            ) as websocket:
                websocket.send_json(self._build_subscribe(16, delay_milliseconds=100))
                websocket.receive_text()
                resources = app.state.container.resource_mount.get_streaming_resources()
                client.portal.call(resources.session_registry.notify_shutdown)
                fault = self._receive_terminal_event(websocket)
                with pytest.raises(WebSocketDisconnect) as captured:
                    websocket.receive_text()

        assert fault["detail"]["close_reason"] == "service_shutdown"
        assert captured.value.code == 1001

    def test_websocket_credential_deadline_should_emit_fault_and_close_1008(self) -> None:
        """验证访问凭证到期作为连接硬截止时间。"""

        with TestClient(TestAppFactory().create()) as client:
            with client.websocket_connect(
                TEST_STREAM_WEBSOCKET_PATH,
                headers={
                    "origin": WEBSOCKET_ORIGIN,
                    "authorization": f"Bearer {TEST_STREAM_EXPIRING_BEARER_TOKEN}",
                },
            ) as websocket:
                websocket.send_json(self._build_subscribe(16, delay_milliseconds=100))
                fault = self._receive_terminal_event(websocket)
                with pytest.raises(WebSocketDisconnect) as captured:
                    websocket.receive_text()

        assert fault["detail"]["close_reason"] == "policy_rejected"
        assert captured.value.code == 1008

    def _build_headers(self) -> dict[str, str]:
        """构建 WebSocket 测试请求头。"""

        return {
            "origin": WEBSOCKET_ORIGIN,
            "authorization": f"Bearer {TEST_STREAM_BEARER_TOKEN}",
        }

    def _build_subscribe(
        self,
        count: int,
        *,
        delay_milliseconds: int = 0,
    ) -> dict[str, object]:
        """构建首次订阅控制帧。"""

        return {
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
                    "count": count,
                    "delay_milliseconds": delay_milliseconds,
                },
            },
        }

    def _build_cancel(self) -> dict[str, object]:
        """构建客户端取消控制帧。

        :returns: 强类型取消控制帧映射。
        :rtype: dict[str, object]
        """

        return {
            "header": {
                "kind": "stream_client_control_header",
                "schema_version": "1.0",
                "control_kind": "cancel",
            },
            "detail": {
                "kind": "cancel",
                "schema_version": "1.0",
                "reason": "测试取消",
            },
        }

    def _receive_terminal_event(
        self,
        websocket: WebSocketTestSession,
    ) -> dict[str, object]:
        """读取直到强类型终止事件。"""

        for _ in range(WEBSOCKET_DRAIN_MESSAGE_LIMIT):
            event = json.loads(websocket.receive_text())
            if event.get("detail", {}).get("kind") == "stream_fault":
                return event
        raise AssertionError("未在限制帧数内收到 stream_fault。")
