"""
Prometheus 指标路由基础设施模块。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from time import perf_counter

from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from src.infrastructure.observability.prometheus_metrics_registry import (
    HttpRequestMetric,
    PrometheusMetricsRegistry,
    RuntimeReadyMetric,
)

APP_READY_STATE_NAME = "ready"
DEFAULT_UNMATCHED_ROUTE_PATH = "unmatched"
ROUTE_SCOPE_KEY = "route"
ROUTE_PATH_ATTRIBUTE_NAME = "path"
METRICS_HTTP_METHODS = ["GET"]


class PrometheusHttpMetricsMiddleware(BaseHTTPMiddleware):
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

        super().__init__(app)
        self._registry = registry

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """
        记录 HTTP 请求指标并继续请求处理。

        :param request: 当前 HTTP 请求。
        :type request: Request
        :param call_next: 后续中间件或路由调用器。
        :type call_next: Callable[[Request], Awaitable[Response]]
        :returns: HTTP 响应。
        :rtype: Response
        """

        started_at = perf_counter()
        response = await call_next(request)
        self._registry.record_http_request(
            HttpRequestMetric(
                method=request.method,
                path=self._resolve_route_path(request),
                status_code=response.status_code,
                duration_seconds=perf_counter() - started_at,
            )
        )
        return response

    def _resolve_route_path(self, request: Request) -> str:
        """
        解析低基数路由路径。

        :param request: 当前 HTTP 请求。
        :type request: Request
        :returns: 路由模板路径。
        :rtype: str
        """

        route = request.scope.get(ROUTE_SCOPE_KEY)
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
    ) -> None:
        """
        初始化 Prometheus 指标路由。

        :param registry: Prometheus 指标注册器。
        :type registry: PrometheusMetricsRegistry
        :param metrics_path: 指标出口路径。
        :type metrics_path: str
        :param include_runtime_metrics: 是否输出运行时指标。
        :type include_runtime_metrics: bool
        :returns: 无返回值。
        :rtype: None
        """

        self._registry = registry
        self._metrics_path = metrics_path
        self._include_runtime_metrics = include_runtime_metrics
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
