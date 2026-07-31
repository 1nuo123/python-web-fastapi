"""流完成感知的耗时探针中间件。"""

from __future__ import annotations

import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

MIDDLEWARE_TRACE_NAME = "elapsed_probe"
ELAPSED_MILLISECONDS_HEADER_NAME = "X-Elapsed-Ms"
ELAPSED_MILLISECONDS_STATE_NAME = "elapsed_milliseconds"
MILLISECONDS_PER_SECOND = 1000
HTTP_RESPONSE_START_MESSAGE = "http.response.start"
HTTP_RESPONSE_BODY_MESSAGE = "http.response.body"
WEBSOCKET_CLOSE_MESSAGE = "websocket.close"
SUPPORTED_SCOPE_TYPES = frozenset({"http", "websocket"})


class ElapsedProbeMiddleware:
    """在真实 HTTP 流结束或 WebSocket 关闭后记录耗时。"""

    def __init__(self, app: ASGIApp) -> None:
        """初始化纯 ASGI 耗时探针。"""

        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """执行连接生命周期耗时采集。"""

        if scope["type"] not in SUPPORTED_SCOPE_TYPES:
            await self._app(scope, receive, send)
            return
        state = scope.setdefault("state", {})
        trace = state.setdefault("middleware_trace", [])
        trace.append(MIDDLEWARE_TRACE_NAME)
        started_at = time.perf_counter()
        completion_recorded = False

        async def send_with_elapsed_header(message: Message) -> None:
            nonlocal completion_recorded
            if message["type"] == HTTP_RESPONSE_START_MESSAGE:
                elapsed_milliseconds = (time.perf_counter() - started_at) * MILLISECONDS_PER_SECOND
                headers = list(message.get("headers", []))
                headers.append(
                    (
                        ELAPSED_MILLISECONDS_HEADER_NAME.lower().encode(),
                        f"{elapsed_milliseconds:.2f}".encode(),
                    )
                )
                message["headers"] = headers
            if (
                message["type"] == HTTP_RESPONSE_BODY_MESSAGE
                and not bool(message.get("more_body", False))
            ) or message["type"] == WEBSOCKET_CLOSE_MESSAGE:
                state[ELAPSED_MILLISECONDS_STATE_NAME] = (
                    time.perf_counter() - started_at
                ) * MILLISECONDS_PER_SECOND
                completion_recorded = True
            await send(message)

        try:
            await self._app(scope, receive, send_with_elapsed_header)
        finally:
            if not completion_recorded:
                state[ELAPSED_MILLISECONDS_STATE_NAME] = (
                    time.perf_counter() - started_at
                ) * MILLISECONDS_PER_SECOND
