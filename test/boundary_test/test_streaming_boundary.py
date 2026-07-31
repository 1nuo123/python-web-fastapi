"""统一流式边界测试。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.websockets import WebSocketDisconnect

from src.api.testing.streaming_test_route_binder import (
    TEST_STREAM_BEARER_TOKEN,
    TEST_STREAM_WEBSOCKET_PATH,
)
from src.api.testing.test_app_factory import TestAppFactory
from src.core.stream_contract.stream_delivery_contract import StreamCollectionLimit
from src.core.stream_contract.stream_runtime_contract import (
    LocalStreamRuntimeDetail,
    StreamRuntimeEnvelope,
    StreamRuntimeHeader,
    StreamRuntimeMode,
)


class TestStreamingBoundary:
    """统一流式边界测试集合。"""

    @pytest.mark.parametrize("field_name", ["max_events", "max_bytes", "timeout_seconds"])
    def test_collection_limit_when_zero_should_reject(self, field_name: str) -> None:
        """验证聚合三重限制均拒绝零值。"""

        values: dict[str, int | float] = {
            "max_events": 1,
            "max_bytes": 1,
            "timeout_seconds": 1.0,
        }
        values[field_name] = 0

        with pytest.raises(ValidationError):
            StreamCollectionLimit.model_validate(values)

    def test_runtime_when_dimension_quota_exceeds_global_should_reject(self) -> None:
        """验证维度配额不得超过全局配额。"""

        values = self._build_runtime_detail_values()
        values["max_sessions"] = 1
        values["max_sessions_per_subject"] = 2

        with pytest.raises(ValidationError):
            LocalStreamRuntimeDetail.model_validate(values)

    def test_runtime_when_collection_bytes_less_than_event_should_reject(self) -> None:
        """验证聚合字节上限不得小于单事件上限。"""

        values = self._build_runtime_detail_values()
        values["max_event_bytes"] = 1024
        values["collection_max_bytes"] = 512

        with pytest.raises(ValidationError):
            LocalStreamRuntimeDetail.model_validate(values)

    def test_runtime_when_mode_mismatches_detail_should_reject(self) -> None:
        """验证运行时 mode 与 detail.kind 必须一致。"""

        with pytest.raises(ValidationError):
            StreamRuntimeEnvelope(
                header=StreamRuntimeHeader(
                    mode=StreamRuntimeMode.REDIS,
                    enabled=True,
                ),
                detail=LocalStreamRuntimeDetail.model_validate(self._build_runtime_detail_values()),
            )

    def test_websocket_when_message_exceeds_limit_should_close_1009(self) -> None:
        """验证 WebSocket 超大控制帧映射到 1009。"""

        with TestClient(TestAppFactory().create()) as client:
            with client.websocket_connect(
                TEST_STREAM_WEBSOCKET_PATH,
                headers={
                    "origin": "http://testserver",
                    "authorization": f"Bearer {TEST_STREAM_BEARER_TOKEN}",
                },
            ) as websocket:
                websocket.send_text("x" * 9000)
                with pytest.raises(WebSocketDisconnect) as captured:
                    websocket.receive_text()

        assert captured.value.code == 1009

    def _build_runtime_detail_values(self) -> dict[str, object]:
        """构建合法最小流运行时扩展。"""

        return {
            "queue_capacity": 1,
            "send_timeout_seconds": 0.1,
            "max_duration_seconds": 1.0,
            "max_event_bytes": 128,
            "collection_max_events": 1,
            "collection_max_bytes": 128,
            "collection_timeout_seconds": 1.0,
            "max_sessions": 4,
            "max_sessions_per_subject": 1,
            "max_sessions_per_ip": 2,
            "max_sessions_per_operation": 2,
            "ticket_ttl_seconds": 1,
            "replay_ttl_seconds": 1,
            "replay_max_events": 1,
            "sse_heartbeat_seconds": 1,
            "sse_retry_milliseconds": 1,
            "websocket_max_message_bytes": 128,
            "websocket_ping_interval_seconds": 1.0,
            "websocket_ping_timeout_seconds": 1.0,
            "shutdown_grace_seconds": 1.0,
            "allowed_origins": ["http://testserver"],
            "require_browser_ticket": False,
        }
