"""Windows Credential Manager 中的 Agent 设备凭据存储。"""

from __future__ import annotations

from typing import Final, Protocol

import keyring
from keyring.errors import PasswordDeleteError

AGENT_CREDENTIAL_SERVICE_NAME: Final = "CodexRemoteAgent"


class AgentSecretNotFoundError(LookupError):
    """Windows 安全存储中不存在指定 Agent 凭据。"""


class AgentSecretStorePort(Protocol):
    """Agent 设备 token 安全存储边界。"""

    def read(self, credential_id: str) -> str: ...

    def write(self, credential_id: str, token: str) -> None: ...

    def delete(self, credential_id: str) -> None: ...


class AgentKeyringBackendPort(Protocol):
    """便于隔离测试的 keyring 后端最小边界。"""

    def get_password(self, service: str, username: str) -> str | None: ...

    def set_password(self, service: str, username: str, password: str) -> None: ...

    def delete_password(self, service: str, username: str) -> None: ...


class WindowsAgentSecretStore:
    """通过 keyring 使用当前 Windows 用户的 Credential Manager。"""

    def __init__(self, backend: AgentKeyringBackendPort | None = None) -> None:
        self._backend = backend

    def read(self, credential_id: str) -> str:
        """读取设备 token，日志和异常中不包含 token 原文。"""

        token = self._get_password(credential_id)
        if token is None:
            raise AgentSecretNotFoundError("Agent设备凭据不存在。")
        return token

    def write(self, credential_id: str, token: str) -> None:
        """写入非空设备 token。"""

        if not credential_id.strip() or not token:
            raise ValueError("credential_id和设备token不能为空。")
        if self._backend is None:
            keyring.set_password(AGENT_CREDENTIAL_SERVICE_NAME, credential_id, token)
            return
        self._backend.set_password(AGENT_CREDENTIAL_SERVICE_NAME, credential_id, token)

    def delete(self, credential_id: str) -> None:
        """删除已经吊销的本地设备凭据。"""

        if self._backend is None:
            try:
                keyring.delete_password(AGENT_CREDENTIAL_SERVICE_NAME, credential_id)
            except PasswordDeleteError:
                return
            return
        self._backend.delete_password(AGENT_CREDENTIAL_SERVICE_NAME, credential_id)

    def _get_password(self, credential_id: str) -> str | None:
        if self._backend is None:
            return keyring.get_password(AGENT_CREDENTIAL_SERVICE_NAME, credential_id)
        return self._backend.get_password(AGENT_CREDENTIAL_SERVICE_NAME, credential_id)
