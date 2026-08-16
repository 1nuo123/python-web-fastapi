"""Agent control channel connection retry policy tests."""

from __future__ import annotations

from httpx import HTTPStatusError, RemoteProtocolError, Request
from httpx import Response as HttpResponse
from websockets.datastructures import Headers
from websockets.exceptions import InvalidMessage, InvalidStatus
from websockets.http11 import Response as WebSocketResponse

from src.infrastructure.codex_agent.agent_control_channel import (
    AgentControlConnectionPolicy,
)


class TestAgentControlConnectionPolicy:
    """覆盖 WebSocket 握手状态的重试分类。"""

    def test_control_connection_when_handshake_eof_should_retry(self) -> None:
        exc = InvalidMessage("did not receive a valid HTTP response")

        assert AgentControlConnectionPolicy.should_retry(exc) is True
        assert AgentControlConnectionPolicy.describe(exc) == "InvalidMessage"

    def test_control_connection_when_gateway_unavailable_should_retry(self) -> None:
        exc = InvalidStatus(WebSocketResponse(503, "Service Unavailable", Headers(), b""))

        assert AgentControlConnectionPolicy.should_retry(exc) is True
        assert AgentControlConnectionPolicy.describe(exc) == "HTTP 503"

    def test_control_connection_when_device_credential_rejected_should_not_retry(self) -> None:
        exc = InvalidStatus(WebSocketResponse(403, "Forbidden", Headers(), b""))

        assert AgentControlConnectionPolicy.should_retry(exc) is False
        assert AgentControlConnectionPolicy.describe(exc) == "HTTP 403"


class TestAgentControlConnectionTransportPolicy:
    """覆盖连接票据请求阶段的瞬时 HTTP 传输错误。"""

    def test_remote_protocol_disconnect_should_retry(self) -> None:
        exc = RemoteProtocolError("服务端在发送响应前断开连接。")

        assert AgentControlConnectionPolicy.should_retry(exc) is True
        assert AgentControlConnectionPolicy.describe(exc) == "RemoteProtocolError"

    def test_http_rate_limit_should_retry(self) -> None:
        request = Request("POST", "https://control.test/challenge")
        response = HttpResponse(429, headers={"Retry-After": "120"})
        exc = HTTPStatusError("请求过于频繁。", request=request, response=response)

        assert AgentControlConnectionPolicy.should_retry(exc) is True
        assert AgentControlConnectionPolicy.describe(exc) == "HTTP 429"
        assert AgentControlConnectionPolicy.read_retry_after_seconds(exc) == 120

    def test_http_rate_limit_when_retry_after_invalid_should_use_exponential_backoff(
        self,
    ) -> None:
        request = Request("POST", "https://control.test/challenge")
        response = HttpResponse(429, headers={"Retry-After": "invalid"})
        exc = HTTPStatusError("请求过于频繁。", request=request, response=response)

        assert AgentControlConnectionPolicy.read_retry_after_seconds(exc) is None

    def test_http_credential_rejection_should_not_retry(self) -> None:
        request = Request("POST", "https://control.test/challenge")
        response = HttpResponse(403)
        exc = HTTPStatusError("设备凭据已拒绝。", request=request, response=response)

        assert AgentControlConnectionPolicy.should_retry(exc) is False
        assert AgentControlConnectionPolicy.describe(exc) == "HTTP 403"
