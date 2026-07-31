"""WebSocket 建连前安全准入守卫。"""

from __future__ import annotations

from datetime import datetime
from enum import IntEnum, StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator
from starlette.websockets import WebSocket

from src.application.streaming.stream_access_ticket_service import StreamAccessTicketService
from src.core.stream_contract.stream_event_contract import StreamCloseReason, StreamTransport
from src.infrastructure.streaming.stream_session_registry import (
    StreamSessionIdentity,
    StreamSessionLease,
    StreamSessionRegistryPort,
)

AUTHORIZATION_HEADER_NAME = "authorization"
ORIGIN_HEADER_NAME = "origin"
BEARER_PREFIX = "bearer "
STREAM_TICKET_QUERY_NAME = "ticket"
STREAM_TICKET_SUBJECT_QUERY_NAME = "subject_id"
WEBSOCKET_CLIENT_IP_FALLBACK = "unknown"
WEBSOCKET_STREAM_SUBPROTOCOL = "stream.v1"


class WebSocketCloseCode(IntEnum):
    """统一 WebSocket 关闭码映射。"""

    NORMAL = 1000
    SERVICE_RESTART = 1001
    POLICY_REJECTED = 1008
    MESSAGE_TOO_LARGE = 1009
    INTERNAL_ERROR = 1011
    OVERLOADED = 1013


WEBSOCKET_CLOSE_CODE_BY_REASON = {
    StreamCloseReason.COMPLETED: WebSocketCloseCode.NORMAL,
    StreamCloseReason.CLIENT_CANCELLED: WebSocketCloseCode.NORMAL,
    StreamCloseReason.CLIENT_DISCONNECTED: WebSocketCloseCode.NORMAL,
    StreamCloseReason.TIMEOUT: WebSocketCloseCode.POLICY_REJECTED,
    StreamCloseReason.SLOW_CONSUMER: WebSocketCloseCode.OVERLOADED,
    StreamCloseReason.POLICY_REJECTED: WebSocketCloseCode.POLICY_REJECTED,
    StreamCloseReason.SERVICE_SHUTDOWN: WebSocketCloseCode.SERVICE_RESTART,
    StreamCloseReason.INTERNAL_ERROR: WebSocketCloseCode.INTERNAL_ERROR,
}


class WebSocketCloseMapping(BaseModel):
    """统一终止原因与 WebSocket 关闭码映射。"""

    model_config = ConfigDict(extra="forbid")

    reason: StreamCloseReason
    code: WebSocketCloseCode

    @model_validator(mode="after")
    def validate_mapping(self) -> WebSocketCloseMapping:
        """拒绝不符合冻结映射的关闭码组合。"""

        if WEBSOCKET_CLOSE_CODE_BY_REASON[self.reason] != self.code:
            raise ValueError("WebSocket 终止原因与关闭码映射不一致。")
        return self


class StreamCredentialSource(StrEnum):
    """WebSocket 凭证来源。"""

    BEARER = "bearer"
    TICKET = "ticket"


class WebSocketSecurityEventKind(StrEnum):
    """WebSocket 低基数安全事件类型。"""

    ADMITTED = "admitted"
    REJECTED = "rejected"


class WebSocketAdmissionRequest(BaseModel):
    """WebSocket 准入请求事实快照。"""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1)
    origin: str | None
    client_ip: str = Field(min_length=1)
    operation_name: str = Field(min_length=1)
    offered_subprotocols: tuple[str, ...]


class StreamPrincipalSnapshot(BaseModel):
    """WebSocket 流准入所需最小主体快照。"""

    model_config = ConfigDict(extra="forbid")

    subject_id: str = Field(min_length=1)
    roles: frozenset[str]
    scopes: frozenset[str]
    credential_expires_at: datetime | None


class WebSocketAdmissionPort(Protocol):
    """复用现有认证、授权、IP 与限流事实源的准入端口。"""

    async def authenticate_bearer(self, *, token: str) -> StreamPrincipalSnapshot:
        """认证 Bearer 并返回主体快照。"""

        ...

    async def load_ticket_subject(self, *, subject_id: str) -> StreamPrincipalSnapshot:
        """读取票据绑定主体当前快照。"""

        ...

    async def assert_operation_allowed(
        self,
        *,
        principal: StreamPrincipalSnapshot,
        operation_name: str,
    ) -> None:
        """断言主体有权访问目标操作。"""

        ...

    async def assert_ip_allowed(
        self,
        *,
        websocket: WebSocket,
        client_ip: str,
    ) -> None:
        """断言客户端 IP 未被封禁。"""

        ...

    async def assert_rate_limit(
        self,
        *,
        websocket: WebSocket,
        principal: StreamPrincipalSnapshot,
        client_ip: str,
        operation_name: str,
    ) -> None:
        """断言连接未超过安全限流。"""

        ...

    async def record_security_event(
        self,
        *,
        event_kind: WebSocketSecurityEventKind,
        operation_name: str,
        reason: str,
    ) -> None:
        """记录不包含令牌、票据、正文和连接标识的安全事件。"""

        ...


class WebSocketAdmissionResult(BaseModel):
    """WebSocket 准入结果中可序列化部分。"""

    model_config = ConfigDict(extra="forbid")

    principal: StreamPrincipalSnapshot
    credential_source: StreamCredentialSource
    client_ip: str
    ticket_bound: bool
    credential_expires_at: datetime | None
    lease_id: str = Field(min_length=1)
    subprotocol: str | None


class AuthorizedWebSocketAdmission:
    """包含会话租约的 WebSocket 准入结果。"""

    def __init__(
        self,
        *,
        result: WebSocketAdmissionResult,
        lease: StreamSessionLease,
    ) -> None:
        """初始化准入结果。"""

        self.result = result
        self.lease = lease


class WebSocketConnectionGuard:
    """在 ``accept()`` 前完成安全准入与连接配额申请。"""

    def __init__(
        self,
        *,
        allowed_origins: frozenset[str],
        require_browser_ticket: bool,
        admission_port: WebSocketAdmissionPort,
        ticket_service: StreamAccessTicketService,
        session_registry: StreamSessionRegistryPort,
    ) -> None:
        """初始化 WebSocket 准入守卫。"""

        self._allowed_origins = allowed_origins
        self._require_browser_ticket = require_browser_ticket
        self._admission_port = admission_port
        self._ticket_service = ticket_service
        self._session_registry = session_registry

    async def authorize(
        self,
        *,
        websocket: WebSocket,
        operation_name: str,
    ) -> AuthorizedWebSocketAdmission:
        """执行完整建连前准入。

        :param websocket: 尚未接受的 WebSocket 连接。
        :type websocket: WebSocket
        :param operation_name: 目标流操作名。
        :type operation_name: str
        :returns: 主体快照与会话租约。
        :rtype: AuthorizedWebSocketAdmission
        :raises PermissionError: Origin、凭证、授权、IP 或限流不满足时抛出。
        """

        origin = websocket.headers.get(ORIGIN_HEADER_NAME)
        request = WebSocketAdmissionRequest(
            path=websocket.url.path,
            origin=origin,
            client_ip=(
                websocket.client.host
                if websocket.client is not None
                else WEBSOCKET_CLIENT_IP_FALLBACK
            ),
            operation_name=operation_name,
            offered_subprotocols=tuple(websocket.scope.get("subprotocols", [])),
        )
        if (
            request.offered_subprotocols
            and WEBSOCKET_STREAM_SUBPROTOCOL not in request.offered_subprotocols
        ):
            raise PermissionError("WebSocket 子协议不受支持。")
        if origin is not None and origin not in self._allowed_origins:
            await self._admission_port.record_security_event(
                event_kind=WebSocketSecurityEventKind.REJECTED,
                operation_name=operation_name,
                reason="origin_rejected",
            )
            raise PermissionError("WebSocket Origin 不在允许清单中。")
        client_ip = request.client_ip
        await self._admission_port.assert_ip_allowed(
            websocket=websocket,
            client_ip=client_ip,
        )
        principal, credential_source = await self._authenticate(
            websocket=websocket,
            operation_name=operation_name,
            client_ip=client_ip,
        )
        await self._admission_port.assert_operation_allowed(
            principal=principal,
            operation_name=operation_name,
        )
        await self._admission_port.assert_rate_limit(
            websocket=websocket,
            principal=principal,
            client_ip=client_ip,
            operation_name=operation_name,
        )
        lease = await self._session_registry.acquire(
            identity=StreamSessionIdentity(
                subject_id=principal.subject_id,
                client_ip=client_ip,
                operation_name=operation_name,
                transport=StreamTransport.WEBSOCKET,
            )
        )
        await self._admission_port.record_security_event(
            event_kind=WebSocketSecurityEventKind.ADMITTED,
            operation_name=operation_name,
            reason="admitted",
        )
        return AuthorizedWebSocketAdmission(
            result=WebSocketAdmissionResult(
                principal=principal,
                credential_source=credential_source,
                client_ip=client_ip,
                ticket_bound=credential_source is StreamCredentialSource.TICKET,
                credential_expires_at=principal.credential_expires_at,
                lease_id=lease.session_id,
                subprotocol=(
                    WEBSOCKET_STREAM_SUBPROTOCOL
                    if WEBSOCKET_STREAM_SUBPROTOCOL in request.offered_subprotocols
                    else None
                ),
            ),
            lease=lease,
        )

    async def _authenticate(
        self,
        *,
        websocket: WebSocket,
        operation_name: str,
        client_ip: str,
    ) -> tuple[StreamPrincipalSnapshot, StreamCredentialSource]:
        """按 Bearer 或单次票据认证连接。"""

        authorization = websocket.headers.get(AUTHORIZATION_HEADER_NAME)
        if authorization is not None and authorization.lower().startswith(BEARER_PREFIX):
            if (
                self._require_browser_ticket
                and websocket.headers.get(ORIGIN_HEADER_NAME) is not None
            ):
                raise PermissionError("浏览器 WebSocket 连接必须使用单次票据。")
            token = authorization[len(BEARER_PREFIX) :].strip()
            if token == "":
                raise PermissionError("Bearer 凭证为空。")
            principal = await self._admission_port.authenticate_bearer(token=token)
            return principal, StreamCredentialSource.BEARER
        ticket = websocket.query_params.get(STREAM_TICKET_QUERY_NAME)
        subject_id = websocket.query_params.get(STREAM_TICKET_SUBJECT_QUERY_NAME)
        if ticket is None or subject_id is None:
            raise PermissionError("WebSocket 连接缺少有效凭证。")
        principal = await self._admission_port.load_ticket_subject(subject_id=subject_id)
        consumed = await self._ticket_service.consume(
            ticket=ticket,
            subject_id=principal.subject_id,
            operation_name=operation_name,
            client_ip=client_ip,
        )
        if not consumed:
            raise PermissionError("WebSocket 单次票据无效或已消费。")
        return principal, StreamCredentialSource.TICKET
