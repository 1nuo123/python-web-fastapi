"""
Prometheus 指标路由基础设施模块。
"""

from __future__ import annotations

from time import perf_counter
from typing import Protocol

from fastapi import FastAPI, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.infrastructure.observability.prometheus_metrics_registry import (
    HttpRequestMetric,
    PrometheusMetricsRegistry,
    RuntimeReadyMetric,
)

APP_READY_STATE_NAME = "ready"


class RuntimeSaturationProbe(Protocol):
    """
    运行时饱和度刷新探针协议。
    """

    def refresh_runtime_saturation(self) -> None:
        """
        刷新运行时饱和度指标。

        :returns: 无返回值。
        :rtype: None
        """


DEFAULT_UNMATCHED_ROUTE_PATH = "unmatched"
ROUTE_SCOPE_KEY = "route"
ROUTE_PATH_ATTRIBUTE_NAME = "path"
METRICS_HTTP_METHODS = ["GET"]


class PrometheusHttpMetricsMiddleware:
    """
    Prometheus HTTP 指标中间件。
    """

    def __init__(self, app: ASGIApp, registry: PrometheusMetricsRegistry) -> None:
        """
        初始化 Prometheus HTTP 指标中间件。

        :param app: ASGI 应用实例。
        :type app: ASGIApp
        :param registry: Prometheus 指标注册器。
        :type registry: PrometheusMetricsRegistry
        :returns: 无返回值。
        :rtype: None
        """

        self._app = app
        self._registry = registry

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """
        记录 HTTP 请求指标并继续请求处理。

        :param scope: ASGI 作用域。
        :type scope: Scope
        :param receive: ASGI 接收函数。
        :type receive: Receive
        :param send: ASGI 发送函数。
        :type send: Send
        """

        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        started_at = perf_counter()
        status_code = 500

        async def send_with_status(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
            await send(message)

        try:
            await self._app(scope, receive, send_with_status)
        finally:
            self._registry.record_http_request(
                HttpRequestMetric(
                    method=str(scope.get("method", "UNKNOWN")),
                    path=self._resolve_route_path(scope),
                    status_code=status_code,
                    duration_seconds=perf_counter() - started_at,
                )
            )

    def _resolve_route_path(self, scope: Scope) -> str:
        """
        解析低基数路由路径。

        :param scope: 当前 HTTP ASGI 作用域。
        :type scope: Scope
        :returns: 路由模板路径。
        :rtype: str
        """

        route = scope.get(ROUTE_SCOPE_KEY)
        route_path = getattr(route, ROUTE_PATH_ATTRIBUTE_NAME, None)
        if isinstance(route_path, str):
            return route_path
        return DEFAULT_UNMATCHED_ROUTE_PATH


class PrometheusMetricsRoute:
    """
    Prometheus 指标路由。
    """

    def __init__(
        self,
        *,
        registry: PrometheusMetricsRegistry,
        metrics_path: str,
        include_runtime_metrics: bool,
        saturation_probe: RuntimeSaturationProbe | None = None,
    ) -> None:
        """
        初始化 Prometheus 指标路由。

        :param registry: Prometheus 指标注册器。
        :type registry: PrometheusMetricsRegistry
        :param metrics_path: 指标出口路径。
        :type metrics_path: str
        :param include_runtime_metrics: 是否输出运行时指标。
        :type include_runtime_metrics: bool
        :param saturation_probe: 运行时饱和度刷新探针；``None`` 时抓取不刷新饱和度。
        :type saturation_probe: RuntimeSaturationProbe | None
        :returns: 无返回值。
        :rtype: None
        """

        self._registry = registry
        self._metrics_path = metrics_path
        self._include_runtime_metrics = include_runtime_metrics
        self._saturation_probe = saturation_probe
        self._app: FastAPI | None = None

    def bind(self, app: FastAPI) -> None:
        """
        绑定 Prometheus 指标路由。

        :param app: 当前 FastAPI 应用。
        :type app: FastAPI
        :returns: 无返回值。
        :rtype: None
        """

        self._app = app
        app.add_api_route(
            self._metrics_path,
            self.read_metrics,
            methods=METRICS_HTTP_METHODS,
            include_in_schema=False,
        )

    async def read_metrics(self) -> Response:
        """
        读取 Prometheus 指标文本。

        :returns: Prometheus 文本响应。
        :rtype: Response
        """

        if self._include_runtime_metrics:
            self._registry.set_runtime_ready(RuntimeReadyMetric(ready=self._read_app_ready()))
        if self._saturation_probe is not None:
            self._saturation_probe.refresh_runtime_saturation()
        return Response(
            content=self._registry.render(),
            media_type=self._registry.get_content_type(),
        )

    def _read_app_ready(self) -> bool:
        """
        读取应用 ready 状态。

        :returns: 应用 ready 状态。
        :rtype: bool
        """

        if self._app is None:
            return False
        return bool(getattr(self._app.state, APP_READY_STATE_NAME, False))
