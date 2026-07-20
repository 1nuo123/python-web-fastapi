"""
访问日志中间件基础设施模块。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

if TYPE_CHECKING:
    from src.infrastructure.shared_resource_mount import SharedResourceMount


class AccessLogMiddleware(BaseHTTPMiddleware):
    """
    访问日志中间件，负责拦截并增强请求链路。
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        resource_mount: SharedResourceMount,
        logger: logging.Logger,
    ) -> None:
        """
        初始化访问日志中间件。

        :param app: 当前 FastAPI 或 ASGI 应用实例。
        :type app: ASGIApp
        :param resource_mount: 共享资源挂载点，用于构建和发送结构化日志事件。
        :type resource_mount: SharedResourceMount
        :param logger: 当前组件使用的日志记录器。
        :type logger: logging.Logger
        :returns: 无返回值。
        :rtype: None
        """

        super().__init__(app)
        self._resource_mount = resource_mount
        self._logger = logger

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        """
        分发当前请求或任务。

        :param request: 当前 HTTP 请求对象，用于读取状态、请求头和依赖。
        :type request: Request
        :param call_next: 当前步骤使用的调用next参数。
        :type call_next: RequestResponseEndpoint
        :returns: 返回当前操作结果。
        :rtype: Response
        """

        request.state.middleware_trace.append("access_log")
        response = await call_next(request)
        elapsed_milliseconds = getattr(request.state, "elapsed_milliseconds", 0.0)
        log_event_builder = self._resource_mount.get_log_event_builder()
        request_context = log_event_builder.build_request_context(request)
        route = request.scope.get("route")
        route_name = None if route is None else getattr(route, "name", None)
        event = log_event_builder.build_access_event(
            request_context=request_context,
            status_code=response.status_code,
            elapsed_milliseconds=elapsed_milliseconds,
            route_name=route_name,
        )
        self._resource_mount.emit_log_event(event)
        self._logger.info(
            "请求完成：%s %s -> %s", request.method, request.url.path, response.status_code
        )
        return response
