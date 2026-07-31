"""覆盖 HTTP 与 WebSocket 完整生命周期的请求作用域中间件。"""

from __future__ import annotations

import time
import uuid

from starlette.requests import HTTPConnection
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.core.http_contract.request_scope_contract import RequestScope
from src.infrastructure.context.request_context_manager_impl import RequestContextManagerImpl
from src.infrastructure.fastapi_otel_bridge import FastApiOtelBridge

REQUEST_ID_HEADER = "X-Request-ID"
TRACE_ID_HEADER = "X-Trace-ID"
REQUEST_SCOPE_STATE_KEY = "request_scope"
MIDDLEWARE_TRACE_STATE_KEY = "middleware_trace"
HTTP_SCOPE_TYPE = "http"
WEBSOCKET_SCOPE_TYPE = "websocket"
HTTP_RESPONSE_START_MESSAGE = "http.response.start"


class RequestScopeMiddleware:
    """为 HTTP 与 WebSocket 建立持续到最后一帧的请求作用域。"""

    def __init__(
        self,
        app: ASGIApp,
        *,
        request_context_manager: RequestContextManagerImpl,
        telemetry_bridge: FastApiOtelBridge,
    ) -> None:
        """初始化纯 ASGI 请求作用域中间件。"""

        self._app = app
        self._request_context_manager = request_context_manager
        self._telemetry_bridge = telemetry_bridge

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """处理 ASGI 连接完整生命周期。

        :param scope: ASGI 作用域。
        :type scope: Scope
        :param receive: ASGI 接收函数。
        :type receive: Receive
        :param send: ASGI 发送函数。
        :type send: Send
        """

        if scope["type"] not in (HTTP_SCOPE_TYPE, WEBSOCKET_SCOPE_TYPE):
            await self._app(scope, receive, send)
            return
        request = HTTPConnection(scope)
        request_id = request.headers.get(REQUEST_ID_HEADER, str(uuid.uuid4()))
        trace_id = self._telemetry_bridge.read_trace_id(request)
        request_scope = RequestScope(
            request_id=request_id,
            trace_id=trace_id,
            request_time_epoch=int(time.time()),
            request_path=scope.get("path", ""),
            request_method=(
                scope.get("method", "WEBSOCKET")
                if scope["type"] == HTTP_SCOPE_TYPE
                else "WEBSOCKET"
            ),
        )
        state = scope.setdefault("state", {})
        state[MIDDLEWARE_TRACE_STATE_KEY] = ["request_scope"]
        state[REQUEST_SCOPE_STATE_KEY] = request_scope
        self._request_context_manager.set_current_scope(request_scope)

        async def send_with_scope(message: Message) -> None:
            if message["type"] == HTTP_RESPONSE_START_MESSAGE:
                headers = list(message.get("headers", []))
                headers.append((REQUEST_ID_HEADER.lower().encode(), request_id.encode()))
                if trace_id is not None:
                    headers.append((TRACE_ID_HEADER.lower().encode(), trace_id.encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self._app(scope, receive, send_with_scope)
        finally:
            self._request_context_manager.clear_current_scope()
