"""Agent设备认证与用户JWT Bearer分流单元测试。"""

from __future__ import annotations

import pytest
from starlette.requests import Request

from src.core.codex_contract.agent_device_auth_contract import AgentDevicePrincipal
from src.infrastructure.auth.oauth2_scheme_provider import OAuth2SchemeProvider
from src.infrastructure.codex.agent_device_authentication import (
    AgentDeviceAuthenticationError,
    AgentDeviceAuthenticationGuard,
)


class StaticAgentDeviceVerifier:
    """只接受一个测试设备token。"""

    def verify(self, token: str) -> AgentDevicePrincipal | None:
        """验证测试设备token。"""

        if token != "device-secret":
            return None
        return AgentDevicePrincipal(
            credential_id="credential-1",
            host_id="host-1",
            owner_subject_id="owner-1",
        )


class TestAgentDeviceAuthenticationUnit:
    """HTTP scheme与Agent WebSocket专用守卫测试。"""

    def test_http_codex_agent_scheme_should_bypass_user_bearer_parser(self) -> None:
        """验证CodexAgent设备token不会被现有用户JWT中间件提取。"""

        request = self._build_request("CodexAgent device-secret")

        user_token = OAuth2SchemeProvider().extract_bearer_token(request)
        principal = self._build_guard().authenticate_http(request.headers)

        assert user_token is None
        assert principal.host_id == "host-1"

    def test_http_user_bearer_should_not_pass_agent_device_guard(self) -> None:
        """验证普通用户Bearer不能用于Agent内部HTTP接口。"""

        request = self._build_request("Bearer user-jwt")

        assert OAuth2SchemeProvider().extract_bearer_token(request) == "user-jwt"
        with pytest.raises(AgentDeviceAuthenticationError):
            self._build_guard().authenticate_http(request.headers)

    def test_websocket_bearer_should_require_device_verifier_match(self) -> None:
        """验证专用Agent WebSocket即使使用Bearer也必须命中设备凭据。"""

        guard = self._build_guard()

        principal = guard.authenticate_websocket({"Authorization": "Bearer device-secret"})

        assert principal.credential_id == "credential-1"
        with pytest.raises(AgentDeviceAuthenticationError):
            guard.authenticate_websocket({"Authorization": "Bearer user-jwt"})

    def _build_guard(self) -> AgentDeviceAuthenticationGuard:
        """构建设备认证守卫。"""

        return AgentDeviceAuthenticationGuard(verifier=StaticAgentDeviceVerifier())

    def _build_request(self, authorization: str) -> Request:
        """构建带认证header的最小Starlette请求。"""

        return Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/internal/codex-agents/rotate-credential",
                "headers": [(b"authorization", authorization.encode("utf-8"))],
            }
        )
