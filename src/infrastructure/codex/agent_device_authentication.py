"""Agent内部HTTP与WebSocket认证分流守卫。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from src.core.codex_contract.agent_device_auth_contract import (
    AgentDeviceCredentialVerifierPort,
    AgentDevicePrincipal,
)

AUTHORIZATION_HEADER_NAME: Final = "authorization"
CODEX_AGENT_HTTP_SCHEME: Final = "codexagent"
AGENT_WEBSOCKET_BEARER_SCHEME: Final = "bearer"


class AgentDeviceAuthenticationError(PermissionError):
    """Agent设备认证失败。"""


class AgentDeviceAuthenticationGuard:
    """确保Agent HTTP凭据不进入现有用户JWT Bearer解析路径。"""

    def __init__(self, *, verifier: AgentDeviceCredentialVerifierPort) -> None:
        """初始化设备token验证守卫。"""

        self._verifier = verifier

    def authenticate_http(self, headers: Mapping[str, str]) -> AgentDevicePrincipal:
        """只接受独立的 ``CodexAgent`` HTTP认证scheme。"""

        token = self._extract_token(headers, expected_scheme=CODEX_AGENT_HTTP_SCHEME)
        return self._verify(token)

    def authenticate_websocket(self, headers: Mapping[str, str]) -> AgentDevicePrincipal:
        """在专用Agent WebSocket端点accept前验证Bearer设备token。"""

        token = self._extract_token(headers, expected_scheme=AGENT_WEBSOCKET_BEARER_SCHEME)
        return self._verify(token)

    def _verify(self, token: str) -> AgentDevicePrincipal:
        """调用设备摘要验证端口并归一化失败。"""

        principal = self._verifier.verify(token)
        if principal is None:
            raise AgentDeviceAuthenticationError("Agent设备凭据无效或已吊销。")
        return principal

    def _extract_token(
        self,
        headers: Mapping[str, str],
        *,
        expected_scheme: str,
    ) -> str:
        """按大小写不敏感header和scheme提取非空token。"""

        authorization = next(
            (value for name, value in headers.items() if name.lower() == AUTHORIZATION_HEADER_NAME),
            None,
        )
        if authorization is None:
            raise AgentDeviceAuthenticationError("缺少Agent设备凭据。")
        parts = authorization.strip().split(" ", 1)
        if len(parts) != 2 or parts[0].lower() != expected_scheme:
            raise AgentDeviceAuthenticationError("Agent设备认证scheme无效。")
        token = parts[1].strip()
        if not token:
            raise AgentDeviceAuthenticationError("Agent设备凭据为空。")
        return token
