"""
FastAPIOpenTelemetry桥接器基础设施模块。
"""

from __future__ import annotations

from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from starlette.requests import HTTPConnection

from src.core.http_contract.runtime_resource_contract import TelemetryBridgeState
from src.infrastructure.settings.application_settings import OtelRuntimeSettings

TRACEPARENT_HEADER = "traceparent"
TRACE_ID_HEADER = "X-Trace-ID"


class FastApiOtelBridge:
    """
    FastAPIOpenTelemetry桥接器，负责连接外部基础设施与应用对象。
    """

    def __init__(self, runtime_settings: OtelRuntimeSettings) -> None:
        """
        初始化FastAPIOpenTelemetry桥接器。

        :param runtime_settings: ``runtime_settings`` 配置对象。约束：需符合 ``OtelRuntimeSettings`` 注解。
        :type runtime_settings: OtelRuntimeSettings
        :returns: 无返回值。
        :rtype: None
        """

        self._runtime_settings = runtime_settings
        self._state = TelemetryBridgeState(
            enabled=runtime_settings.enabled,
            no_op=not runtime_settings.enabled,
        )

    def instrument_app(self, app: FastAPI) -> None:
        """
        注入应用。

        :param app: 当前 FastAPI 或 ASGI 应用实例。约束：需符合 ``FastAPI`` 注解。
        :type app: FastAPI
        :returns: 无返回值。
        :rtype: None
        """

        if self._runtime_settings.enabled:
            FastAPIInstrumentor.instrument_app(app)

    def read_trace_id(self, request: HTTPConnection) -> str | None:
        """
        读取跟踪标识。

        :param request: 当前 HTTP 请求对象，用于读取状态、请求头和依赖。约束：需符合 ``Request`` 注解。
        :type request: HTTPConnection
        :returns: 返回读取到的对象或状态快照。
        :rtype: str | None
        """

        if not self._runtime_settings.enabled:
            return request.headers.get(TRACE_ID_HEADER)
        traceparent_value = request.headers.get(TRACEPARENT_HEADER)
        if traceparent_value is None:
            return request.headers.get(TRACE_ID_HEADER)
        trace_segments = traceparent_value.split("-")
        if len(trace_segments) >= 2:
            return trace_segments[1]
        return request.headers.get(TRACE_ID_HEADER)

    def get_state(self) -> TelemetryBridgeState:
        """
        获取状态。

        :returns: 返回读取到的对象或状态快照。
        :rtype: TelemetryBridgeState
        """

        return self._state
