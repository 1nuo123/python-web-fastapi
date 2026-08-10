"""Codex Agent 设备凭据仓储应用端口。"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from src.core.codex_contract.agent_device_auth_contract import (
    AgentDevicePrincipal,
    CodexAgentCredentialIssue,
)


class CodexAgentCredentialRepositoryPort(Protocol):
    """按不可逆摘要验证未吊销设备凭据。"""

    def find_active_principal_by_digest(
        self,
        token_digest: str,
    ) -> AgentDevicePrincipal | None: ...

    def add(self, issue: CodexAgentCredentialIssue) -> None: ...

    def rotate(
        self,
        credential_id: UUID,
        issue: CodexAgentCredentialIssue,
        rotated_at: datetime,
    ) -> bool: ...

    def revoke(self, credential_id: UUID, revoked_at: datetime) -> bool: ...
