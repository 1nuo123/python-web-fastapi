"""纯 ASGI 流完成观测路径测试。"""

from __future__ import annotations

import logging
from typing import cast

import pytest
from prometheus_client.parser import text_string_to_metric_families
from starlette.requests import HTTPConnection
from starlette.types import Message, Receive, Scope, Send

from src.core.logging_contract.log_event_contract import LogEventEnvelope
from src.core.stream_contract.stream_event_contract import StreamCloseReason, StreamTransport
from src.infrastructure.context.request_context_manager_impl import RequestContextManagerImpl
from src.infrastructure.fastapi_otel_bridge import FastApiOtelBridge
from src.infrastructure.logging.log_event_builder import LogEventBuilder
from src.infrastructure.middleware_chain.access_log_middleware import AccessLogMiddleware
from src.infrastructure.middleware_chain.elapsed_probe_middleware import ElapsedProbeMiddleware
from src.infrastructure.middleware_chain.request_scope_middleware import RequestScopeMiddleware
from src.infrastructure.observability.prometheus_metrics_registry import (
    PrometheusMetricsRegistry,
)
from src.infrastructure.observability.prometheus_metrics_route import (
    PrometheusHttpMetricsMiddleware,
)
from src.infrastructure.shared_resource_mount import SharedResourceMount
from src.infrastructure.streaming.stream_observation import (
    STREAM_ACCESS_OBSERVATION_STATE_KEY,
    StreamAccessObservation,
)


class ObservationResourceMount:
    """仅记录访问日志事件的共享资源替身。"""

    def __init__(self) -> None:
        self.events: list[LogEventEnvelope] = []
        self.builder = LogEventBuilder()

    def get_log_event_builder(self) -> LogEventBuilder:
        """读取真实日志事件构造器。"""

        return self.builder

    def emit_log_event(self, event: LogEventEnvelope) -> None:
        """记录单个结构化日志事件。"""

        self.events.append(event)


class ObservationTelemetryBridge:
    """固定无 trace 的观测测试桥接器。"""

    def read_trace_id(self, request: HTTPConnection) -> None:
        """测试场景不绑定 trace 标识。"""

        return None


class HttpStreamingAsgiApp:
    """发送两段 HTTP body 的最小流式 ASGI 应用。"""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """发送开始帧、增量帧与最终帧。"""

        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"a", "more_body": True})
        await send({"type": "http.response.body", "body": b"b", "more_body": False})


class WebSocketClosingAsgiApp:
    """接受后主动关闭的最小 WebSocket ASGI 应用。"""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """发送接受与正常关闭帧。"""

        await send({"type": "websocket.accept"})
        await send({"type": "websocket.close", "code": 1000, "reason": ""})


class AsgiMessageRecorder:
    """记录下游 ASGI 消息。"""

    def __init__(self) -> None:
        self.messages: list[Message] = []

    async def send(self, message: Message) -> None:
        """追加单个下游消息。"""

        self.messages.append(message)

    async def receive(self) -> Message:
        """返回一次 HTTP 请求体结束消息。"""

        return {"type": "http.request", "body": b"", "more_body": False}


class TestStreamingAsgiObservationPath:
    """流完成观测纯 ASGI 路径测试集合。"""

    @pytest.mark.asyncio
    async def test_http_final_body_should_record_scope_elapsed_log_and_metric_once(self) -> None:
        """验证最终 body 后作用域、耗时、访问日志和 HTTP 指标各记录一次。"""

        resource_mount = ObservationResourceMount()
        metrics = PrometheusMetricsRegistry()
        scope = cast(
            Scope,
            {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": "POST",
                "scheme": "http",
                "path": "/stream",
                "raw_path": b"/stream",
                "query_string": b"",
                "headers": [],
                "client": ("127.0.0.1", 1),
                "server": ("testserver", 80),
                "state": {
                    STREAM_ACCESS_OBSERVATION_STATE_KEY: StreamAccessObservation(
                        operation_name="observation_test",
                        transport=StreamTransport.SSE,
                        subject_digest="subject-digest",
                        event_count=2,
                        close_reason=StreamCloseReason.COMPLETED,
                    )
                },
            },
        )
        recorder = AsgiMessageRecorder()
        app = RequestScopeMiddleware(
            PrometheusHttpMetricsMiddleware(
                AccessLogMiddleware(
                    ElapsedProbeMiddleware(HttpStreamingAsgiApp()),
                    resource_mount=cast(SharedResourceMount, resource_mount),
                    logger=logging.getLogger(__name__),
                ),
                registry=metrics,
            ),
            request_context_manager=RequestContextManagerImpl(),
            telemetry_bridge=cast(FastApiOtelBridge, ObservationTelemetryBridge()),
        )

        await app(scope, recorder.receive, recorder.send)

        assert "request_scope" in scope["state"]
        assert float(scope["state"]["elapsed_milliseconds"]) >= 0
        assert len(resource_mount.events) == 1
        assert resource_mount.events[0].detail.kind == "stream_access"
        metrics_text = metrics.render().decode()
        request_samples = [
            sample
            for family in text_string_to_metric_families(metrics_text)
            for sample in family.samples
            if sample.name == "fastapi_request_total"
        ]
        assert len(request_samples) == 1
        assert request_samples[0].value == 1.0

    @pytest.mark.asyncio
    async def test_websocket_close_should_record_scope_elapsed_and_access_log_once(self) -> None:
        """验证 WebSocket close 后请求作用域、耗时和流访问日志只记录一次。"""

        resource_mount = ObservationResourceMount()
        scope = cast(
            Scope,
            {
                "type": "websocket",
                "asgi": {"version": "3.0"},
                "scheme": "ws",
                "path": "/stream/ws",
                "raw_path": b"/stream/ws",
                "query_string": b"",
                "headers": [],
                "client": ("127.0.0.1", 1),
                "server": ("testserver", 80),
                "subprotocols": [],
                "state": {
                    STREAM_ACCESS_OBSERVATION_STATE_KEY: StreamAccessObservation(
                        operation_name="observation_test",
                        transport=StreamTransport.WEBSOCKET,
                        subject_digest="subject-digest",
                        event_count=1,
                        close_reason=StreamCloseReason.COMPLETED,
                    )
                },
            },
        )
        recorder = AsgiMessageRecorder()
        app = RequestScopeMiddleware(
            AccessLogMiddleware(
                ElapsedProbeMiddleware(WebSocketClosingAsgiApp()),
                resource_mount=cast(SharedResourceMount, resource_mount),
                logger=logging.getLogger(__name__),
            ),
            request_context_manager=RequestContextManagerImpl(),
            telemetry_bridge=cast(FastApiOtelBridge, ObservationTelemetryBridge()),
        )

        await app(scope, recorder.receive, recorder.send)

        assert "request_scope" in scope["state"]
        assert float(scope["state"]["elapsed_milliseconds"]) >= 0
        assert len(resource_mount.events) == 1
        assert resource_mount.events[0].detail.kind == "stream_access"
