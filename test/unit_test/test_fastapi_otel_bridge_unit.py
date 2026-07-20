"""
FastAPI OpenTelemetry 桥接器单元测试模块。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from starlette.requests import Request

from src.infrastructure.fastapi_otel_bridge import FastApiOtelBridge
from src.infrastructure.settings.application_settings import OtelRuntimeSettings

CUSTOM_TRACE_HEADER_NAME = "X-Trace-ID"
CUSTOM_TRACE_ID = "local-trace-id"
TRACEPARENT_HEADER_NAME = "traceparent"
TRACEPARENT_VALUE = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
TRACEPARENT_TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
SERVICE_NAME = "fastapi-web-skeleton"
OTEL_EXPORTER_ENDPOINT = ""
OTEL_SAMPLE_RATIO = 1.0


class TestFastApiOtelBridgeUnit:
    """
    FastAPI OpenTelemetry 桥接器单元测试集合。
    """

    def test_disabled_settings_should_be_no_op(self) -> None:
        """
        验证默认关闭配置应进入 no-op 状态。
        """

        bridge = FastApiOtelBridge(self._build_settings(enabled=False))

        state = bridge.get_state()

        assert state.enabled is False
        assert state.no_op is True

    def test_enabled_settings_should_instrument_app(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        验证开启配置应调用 FastAPI instrument。
        """

        instrumented_apps: list[FastAPI] = []

        def fake_instrument_app(app: FastAPI) -> None:
            instrumented_apps.append(app)

        monkeypatch.setattr(
            FastAPIInstrumentor,
            "instrument_app",
            fake_instrument_app,
        )
        app = FastAPI()
        bridge = FastApiOtelBridge(self._build_settings(enabled=True))

        bridge.instrument_app(app)

        assert instrumented_apps == [app]

    def test_traceparent_should_take_priority_when_enabled(self) -> None:
        """
        验证启用 OTel 时优先读取 traceparent。
        """

        bridge = FastApiOtelBridge(self._build_settings(enabled=True))
        request = self._build_request(
            [
                (TRACEPARENT_HEADER_NAME, TRACEPARENT_VALUE),
                (CUSTOM_TRACE_HEADER_NAME, CUSTOM_TRACE_ID),
            ]
        )

        assert bridge.read_trace_id(request) == TRACEPARENT_TRACE_ID

    def test_custom_trace_header_should_be_used_when_disabled(self) -> None:
        """
        验证关闭 OTel 时读取自定义 trace 头。
        """

        bridge = FastApiOtelBridge(self._build_settings(enabled=False))
        request = self._build_request([(CUSTOM_TRACE_HEADER_NAME, CUSTOM_TRACE_ID)])

        assert bridge.read_trace_id(request) == CUSTOM_TRACE_ID

    def _build_settings(self, *, enabled: bool) -> OtelRuntimeSettings:
        """
        构建 OTel 运行时配置。

        :param enabled: 是否启用 OTel。
        :type enabled: bool
        :returns: OTel 运行时配置。
        :rtype: OtelRuntimeSettings
        """

        return OtelRuntimeSettings(
            enabled=enabled,
            service_name=SERVICE_NAME,
            exporter_endpoint=OTEL_EXPORTER_ENDPOINT,
            traces_sample_ratio=OTEL_SAMPLE_RATIO,
        )

    def _build_request(self, headers: list[tuple[str, str]]) -> Request:
        """
        构建测试请求。

        :param headers: HTTP 请求头。
        :type headers: list[tuple[str, str]]
        :returns: Starlette 请求对象。
        :rtype: Request
        """

        encoded_headers = [
            (header_name.lower().encode(), header_value.encode())
            for header_name, header_value in headers
        ]
        return Request({"type": "http", "headers": encoded_headers})
