"""HTTP 与 WebSocket 流执行上下文读取器。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import Request, WebSocket

from src.core.auth_contract.authenticated_principal_contract import AuthenticatedPrincipal
from src.core.http_contract.request_scope_contract import RequestScope

ANONYMOUS_STREAM_SUBJECT_ID = "anonymous"
UNKNOWN_STREAM_CLIENT_IP = "unknown"


@dataclass(frozen=True, slots=True)
class StreamRequestIdentity:
    """流请求身份与链路快照。"""

    request_id: str
    trace_id: str | None
    subject_id: str
    client_ip: str


class StreamingContextAccessor:
    """统一读取 HTTP 与 WebSocket 流上下文。"""

    def read_http(self, request: Request, *, require_authenticated: bool) -> StreamRequestIdentity:
        """读取 HTTP 流上下文。

        :param request: 当前 HTTP 请求。
        :type request: Request
        :param require_authenticated: 是否要求已认证主体。
        :type require_authenticated: bool
        :returns: 流请求身份快照。
        :rtype: StreamRequestIdentity
        :raises PermissionError: 要求认证但请求未绑定主体时抛出。
        """

        request_scope = getattr(request.state, "request_scope", None)
        principal = getattr(request.state, "authenticated_principal", None)
        subject_id = self._resolve_subject_id(
            principal=principal,
            require_authenticated=require_authenticated,
        )
        return StreamRequestIdentity(
            request_id=(
                request_scope.request_id
                if isinstance(request_scope, RequestScope)
                else str(uuid.uuid4())
            ),
            trace_id=(request_scope.trace_id if isinstance(request_scope, RequestScope) else None),
            subject_id=subject_id,
            client_ip=(
                request.client.host if request.client is not None else UNKNOWN_STREAM_CLIENT_IP
            ),
        )

    def read_websocket(self, websocket: WebSocket) -> StreamRequestIdentity:
        """读取 WebSocket 链路上下文。

        :param websocket: 当前 WebSocket 连接。
        :type websocket: WebSocket
        :returns: 未包含认证主体的连接链路快照。
        :rtype: StreamRequestIdentity
        """

        request_scope = getattr(websocket.state, "request_scope", None)
        return StreamRequestIdentity(
            request_id=(
                request_scope.request_id
                if isinstance(request_scope, RequestScope)
                else str(uuid.uuid4())
            ),
            trace_id=(request_scope.trace_id if isinstance(request_scope, RequestScope) else None),
            subject_id=ANONYMOUS_STREAM_SUBJECT_ID,
            client_ip=(
                websocket.client.host if websocket.client is not None else UNKNOWN_STREAM_CLIENT_IP
            ),
        )

    def _resolve_subject_id(
        self,
        *,
        principal: object,
        require_authenticated: bool,
    ) -> str:
        """解析 HTTP 主体标识。"""

        if isinstance(principal, AuthenticatedPrincipal):
            return principal.subject_id
        if require_authenticated:
            raise PermissionError("当前流操作要求已认证主体。")
        return ANONYMOUS_STREAM_SUBJECT_ID
