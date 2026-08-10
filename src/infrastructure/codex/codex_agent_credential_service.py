"""控制面 Agent 设备 token 摘要验证服务。"""

from __future__ import annotations

import hashlib

from src.application.ports.codex_control_port import CodexControlPort
from src.core.codex_contract.agent_device_auth_contract import AgentDevicePrincipal


class CodexAgentCredentialService:
    """通过 UoW 只读验证设备 token，数据库不保存原文。"""

    def __init__(self, control_port: CodexControlPort) -> None:
        self._control_port = control_port

    def verify(self, token: str) -> AgentDevicePrincipal | None:
        """摘要设备 token 并读取有效凭据主体。"""

        if not token:
            return None
        token_digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        unit_of_work = self._control_port.create_unit_of_work()
        try:
            repository = self._control_port.create_codex_agent_credential_repository(
                unit_of_work.get_session()
            )
            return repository.find_active_principal_by_digest(token_digest)
        finally:
            unit_of_work.dispose()
