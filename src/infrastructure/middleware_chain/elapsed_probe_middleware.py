"""
耗时探针中间件基础设施模块。
"""

from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

MIDDLEWARE_TRACE_NAME = "elapsed_probe"
ELAPSED_MILLISECONDS_HEADER_NAME = "X-Elapsed-Ms"
MILLISECONDS_PER_SECOND = 1000


class ElapsedProbeMiddleware(BaseHTTPMiddleware):
    """
    耗时探针中间件，负责拦截并增强请求链路。
    """

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

        request.state.middleware_trace.append(MIDDLEWARE_TRACE_NAME)
        start_time = time.perf_counter()
        response = await call_next(request)
        elapsed_milliseconds = (time.perf_counter() - start_time) * MILLISECONDS_PER_SECOND
        request.state.elapsed_milliseconds = elapsed_milliseconds
        response.headers[ELAPSED_MILLISECONDS_HEADER_NAME] = f"{elapsed_milliseconds:.2f}"
        return response
