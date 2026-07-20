"""
请求作用域中间件基础设施模块。
"""

from __future__ import annotations

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from src.infrastructure.context.request_context_manager_impl import RequestContextManagerImpl
from src.infrastructure.fastapi_otel_bridge import FastApiOtelBridge

REQUEST_ID_HEADER = "X-Request-ID"


class RequestScopeMiddleware(BaseHTTPMiddleware):
    """
    请求作用域中间件，负责拦截并增强请求链路。
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        request_context_manager: RequestContextManagerImpl,
        telemetry_bridge: FastApiOtelBridge,
    ) -> None:
        """
        初始化请求作用域中间件。

        :param app: 当前 FastAPI 或 ASGI 应用实例。
        :type app: ASGIApp
        :param request_context_manager: 请求上下文管理器，用于构建和绑定请求作用域。约束：需符合 ``RequestContextManagerImpl`` 注解。
        :type request_context_manager: RequestContextManagerImpl
        :param telemetry_bridge: 遥测桥接器，用于管理 OpenTelemetry 相关状态。约束：需符合 ``FastApiOtelBridge`` 注解。
        :type telemetry_bridge: FastApiOtelBridge
        :returns: 无返回值。
        :rtype: None
        """

        super().__init__(app)
        self._request_context_manager = request_context_manager
        self._telemetry_bridge = telemetry_bridge

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

        request_id = request.headers.get(REQUEST_ID_HEADER, str(uuid.uuid4()))
        trace_id = self._telemetry_bridge.read_trace_id(request)
        request_scope = self._request_context_manager.build_scope(
            request=request,
            request_id=request_id,
            trace_id=trace_id,
            request_time_epoch=int(time.time()),
        )
        request.state.middleware_trace = ["request_scope"]
        request.state.request_scope = request_scope
        self._request_context_manager.set_current_scope(request_scope)
        try:
            response = await call_next(request)
            response.headers[REQUEST_ID_HEADER] = request_id
            if trace_id is not None:
                response.headers["X-Trace-ID"] = trace_id
            return response
        finally:
            self._request_context_manager.clear_current_scope()
