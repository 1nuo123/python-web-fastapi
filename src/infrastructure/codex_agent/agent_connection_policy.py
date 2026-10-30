"""完整连接尝试共用的错误分类与服务端退避提示。"""

import ssl
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from enum import StrEnum

from httpx import HTTPStatusError, TransportError
from websockets.exceptions import InvalidHandshake, InvalidMessage, InvalidStatus

from src.core.codex_contract.agent_connection_contract import (
    AGENT_CONNECTION_REJECTION_HEADER,
    AGENT_CONNECTION_TICKET_EXPIRED,
    AgentConnectionIssue,
)
from src.core.codex_contract.connection_session_contract import (
    CodexConnectionEndKind,
    CodexConnectionFrameTooLargeError,
    CodexConnectionTransportClosed,
)

RETRYABLE_AGENT_HANDSHAKE_STATUS_CODES = frozenset(
    {408, 425, 429, 500, 502, 503, 504, 520, 521, 522, 523, 524}
)


class AgentExecutionStopReason(StrEnum):
    LEASE_EXPIRED = "lease_expired"
    DEVICE_REVOKED = "device_revoked"
    HOST_SWITCHED = "host_switched"
    LOCAL_SHUTDOWN = "local_shutdown"
    EXECUTION_FAILED = "execution_failed"


class AgentControlConnectionPolicy:
    """先识别永久错误，再处理宽泛传输异常；不记录URL或响应正文。"""

    @staticmethod
    def preserve_execution(
        exc: BaseException, *, continuity: bool, lease_valid: bool, process_healthy: bool
    ) -> bool:
        if not (continuity and lease_valid and process_healthy):
            return False
        if isinstance(exc, CodexConnectionTransportClosed):
            return exc.end_kind == CodexConnectionEndKind.TRANSPORT_FAILURE
        return AgentControlConnectionPolicy.should_retry(exc)

    @staticmethod
    def read_status_code(exc: BaseException) -> int | None:
        response = getattr(exc, "response", None)
        value = getattr(response, "status_code", getattr(exc, "status_code", None))
        return value if isinstance(value, int) else None

    @staticmethod
    def issue(exc: BaseException) -> AgentConnectionIssue:
        current: BaseException | None = exc
        seen: set[int] = set()
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            received_close = getattr(current, "rcvd", None)
            if (
                isinstance(current, CodexConnectionFrameTooLargeError)
                or getattr(current, "close_code", None) == 1009
                or getattr(received_close, "code", None) == 1009
            ):
                return AgentConnectionIssue.MESSAGE_TOO_LARGE
            if isinstance(current, ssl.SSLCertVerificationError):
                return AgentConnectionIssue.TLS_VALIDATION_FAILED
            current = current.__cause__ or current.__context__
        status = AgentControlConnectionPolicy.read_status_code(exc)
        headers = getattr(getattr(exc, "response", None), "headers", {})
        if (
            status == 401
            and headers.get(AGENT_CONNECTION_REJECTION_HEADER) == AGENT_CONNECTION_TICKET_EXPIRED
        ):
            return AgentConnectionIssue.ATTEMPT_EXPIRED
        if status == 429:
            return AgentConnectionIssue.RATE_LIMITED
        if status in (525, 526):
            return AgentConnectionIssue.ORIGIN_TLS_FAILED
        if status in (401, 403):
            return AgentConnectionIssue.GATEWAY_POLICY_DENIED
        if status in (404, 405):
            return AgentConnectionIssue.ROUTE_NOT_FOUND
        if status in RETRYABLE_AGENT_HANDSHAKE_STATUS_CODES:
            return AgentConnectionIssue.UPSTREAM_UNAVAILABLE
        if isinstance(exc, PermissionError) or getattr(exc, "close_code", None) in (
            1008,
            4401,
            4403,
        ):
            return AgentConnectionIssue.AUTHORIZATION_REJECTED
        if isinstance(exc, (ValueError, InvalidHandshake)) and not isinstance(exc, InvalidMessage):
            return AgentConnectionIssue.PROTOCOL_INVALID
        if getattr(exc, "close_code", None) in (1002, 1003, 1007, 1010):
            return AgentConnectionIssue.PROTOCOL_INVALID
        if isinstance(exc, (OSError, TimeoutError, TransportError, InvalidMessage)):
            return AgentConnectionIssue.TRANSPORT_UNAVAILABLE
        return AgentConnectionIssue.INTERNAL_FAILURE

    @staticmethod
    def should_retry(exc: BaseException) -> bool:
        if AgentControlConnectionPolicy.issue(exc) == AgentConnectionIssue.ATTEMPT_EXPIRED:
            return True
        if AgentControlConnectionPolicy.issue(exc) not in {
            AgentConnectionIssue.TRANSPORT_UNAVAILABLE,
            AgentConnectionIssue.UPSTREAM_UNAVAILABLE,
            AgentConnectionIssue.RATE_LIMITED,
        }:
            return False
        if isinstance(exc, (HTTPStatusError, InvalidStatus)):
            return (
                AgentControlConnectionPolicy.read_status_code(exc)
                in RETRYABLE_AGENT_HANDSHAKE_STATUS_CODES
            )
        return isinstance(
            exc,
            (OSError, TimeoutError, TransportError, InvalidMessage, CodexConnectionTransportClosed),
        )

    @staticmethod
    def describe(exc: BaseException) -> str:
        if isinstance(exc, CodexConnectionTransportClosed):
            return f"phase={exc.phase} reason={exc.reason_code} close_code={exc.close_code}"
        status = AgentControlConnectionPolicy.read_status_code(exc)
        if status is not None:
            return f"HTTP {status}"
        close_code = getattr(exc, "close_code", None)
        return (
            f"WebSocket close_code={close_code}" if close_code is not None else type(exc).__name__
        )

    @staticmethod
    def read_retry_after_seconds(exc: BaseException) -> float | None:
        headers = getattr(getattr(exc, "response", None), "headers", None)
        raw = headers.get("Retry-After") if headers is not None else None
        if not isinstance(raw, str):
            return None
        try:
            seconds = float(int(raw))
        except (ValueError, OverflowError):
            try:
                date = parsedate_to_datetime(raw)
                if date.tzinfo is None:
                    date = date.replace(tzinfo=UTC)
                seconds = (date - datetime.now(UTC)).total_seconds()
            except (TypeError, ValueError, OverflowError):
                return None
        return max(seconds, 0.0)
