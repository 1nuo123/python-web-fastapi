"""
安全头中间件基础设施模块。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

if TYPE_CHECKING:
    from src.infrastructure.shared_resource_mount import SharedResourceMount

CONTENT_SECURITY_POLICY_HEADER = "Content-Security-Policy"
CONTENT_SECURITY_POLICY_VALUE = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
FRAME_OPTIONS_HEADER = "X-Frame-Options"
FRAME_OPTIONS_VALUE = "DENY"
HSTS_HEADER = "Strict-Transport-Security"
HSTS_VALUE = "max-age=31536000; includeSubDomains"
PERMISSIONS_POLICY_HEADER = "Permissions-Policy"
PERMISSIONS_POLICY_VALUE = "geolocation=(), microphone=(), camera=()"
REFERRER_POLICY_HEADER = "Referrer-Policy"
REFERRER_POLICY_VALUE = "no-referrer"
X_CONTENT_TYPE_OPTIONS_HEADER = "X-Content-Type-Options"
X_CONTENT_TYPE_OPTIONS_VALUE = "nosniff"
MIDDLEWARE_TRACE_HEADER = "X-Middleware-Trace"


class SecurityHeaderMiddleware(BaseHTTPMiddleware):
    """
    安全头中间件，负责拦截并增强请求链路。
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        resource_mount: SharedResourceMount,
    ) -> None:
        """
        初始化安全头中间件。

        :param app: 当前 FastAPI 或 ASGI 应用实例。
        :type app: ASGIApp
        :param resource_mount: 共享资源挂载点。
        :type resource_mount: SharedResourceMount
        :returns: 无返回值。
        :rtype: None
        """

        super().__init__(app)
        self._resource_mount = resource_mount

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

        request.state.middleware_trace.append("security_header")
        response = await call_next(request)
        settings = self._resource_mount.read_runtime_bundle().settings
        if settings.runtime.web.enable_security_headers:
            response.headers[X_CONTENT_TYPE_OPTIONS_HEADER] = X_CONTENT_TYPE_OPTIONS_VALUE
            response.headers[FRAME_OPTIONS_HEADER] = FRAME_OPTIONS_VALUE
            response.headers[REFERRER_POLICY_HEADER] = REFERRER_POLICY_VALUE
            response.headers[PERMISSIONS_POLICY_HEADER] = PERMISSIONS_POLICY_VALUE
            if settings.runtime.security.detail.enable_hsts:
                response.headers[HSTS_HEADER] = HSTS_VALUE
            if settings.runtime.security.detail.enable_csp:
                response.headers[CONTENT_SECURITY_POLICY_HEADER] = CONTENT_SECURITY_POLICY_VALUE
        if settings.runtime.web.include_middleware_trace_header:
            response.headers[MIDDLEWARE_TRACE_HEADER] = ",".join(request.state.middleware_trace)
        return response
