"""流完成感知的访问日志中间件。"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from starlette.requests import HTTPConnection
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.infrastructure.streaming.stream_observation import (
    STREAM_ACCESS_OBSERVATION_STATE_KEY,
    StreamAccessObservation,
)

if TYPE_CHECKING:
    from src.infrastructure.shared_resource_mount import SharedResourceMount

DEFAULT_HTTP_STATUS_CODE = 500
DEFAULT_WEBSOCKET_STATUS_CODE = 101
HTTP_RESPONSE_START_MESSAGE = "http.response.start"
WEBSOCKET_ACCEPT_MESSAGE = "websocket.accept"
SUPPORTED_SCOPE_TYPES = frozenset({"http", "websocket"})


class AccessLogMiddleware:
    """在连接真实结束后写入一次结构化访问日志。"""

    def __init__(
        self,
        app: ASGIApp,
        *,
        resource_mount: SharedResourceMount,
        logger: logging.Logger,
    ) -> None:
        """初始化纯 ASGI 访问日志中间件。"""

        self._app = app
        self._resource_mount = resource_mount
        self._logger = logger

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """执行连接并在结束后记录访问事实。"""

        if scope["type"] not in SUPPORTED_SCOPE_TYPES:
            await self._app(scope, receive, send)
            return
        state = scope.setdefault("state", {})
        trace = state.setdefault("middleware_trace", [])
        trace.append("access_log")
        status_code = (
            DEFAULT_HTTP_STATUS_CODE if scope["type"] == "http" else DEFAULT_WEBSOCKET_STATUS_CODE
        )

        async def send_with_status(message: Message) -> None:
            nonlocal status_code
            if message["type"] == HTTP_RESPONSE_START_MESSAGE:
                status_code = int(message["status"])
            elif message["type"] == WEBSOCKET_ACCEPT_MESSAGE:
                status_code = DEFAULT_WEBSOCKET_STATUS_CODE
            await send(message)

        try:
            await self._app(scope, receive, send_with_status)
        finally:
            request = HTTPConnection(scope)
            elapsed_milliseconds = float(state.get("elapsed_milliseconds", 0.0))
            log_event_builder = self._resource_mount.get_log_event_builder()
            request_context = log_event_builder.build_request_context(request)
            route = scope.get("route")
            route_name = None if route is None else getattr(route, "name", None)
            observation = state.get(STREAM_ACCESS_OBSERVATION_STATE_KEY)
            if isinstance(observation, StreamAccessObservation):
                event = log_event_builder.build_stream_access_event(
                    request_context=request_context,
                    status_code=status_code,
                    elapsed_milliseconds=elapsed_milliseconds,
                    operation_name=observation.operation_name,
                    transport=observation.transport,
                    event_count=observation.event_count,
                    close_reason=observation.close_reason,
                    subject_digest=observation.subject_digest,
                )
            else:
                event = log_event_builder.build_access_event(
                    request_context=request_context,
                    status_code=status_code,
                    elapsed_milliseconds=elapsed_milliseconds,
                    route_name=route_name,
                )
            self._resource_mount.emit_log_event(event)
            self._logger.info(
                "连接完成：%s %s -> %s",
                request_context.request_method,
                request_context.request_path,
                status_code,
            )
