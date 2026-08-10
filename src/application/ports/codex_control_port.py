"""Codex 控制面组合应用端口。"""

from __future__ import annotations

from typing import Protocol

from src.application.ports.codex_agent_credential_repository_port import (
    CodexAgentCredentialRepositoryPort,
)
from src.application.ports.codex_approval_repository_port import CodexApprovalRepositoryPort
from src.application.ports.codex_command_outbox_repository_port import (
    CodexCommandOutboxRepositoryPort,
)
from src.application.ports.codex_device_authorization_audit_repository_port import (
    CodexDeviceAuthorizationAuditRepositoryPort,
)
from src.application.ports.codex_device_key_repository_port import CodexDeviceKeyRepositoryPort
from src.application.ports.codex_host_repository_port import CodexHostRepositoryPort
from src.application.ports.codex_operation_repository_port import CodexOperationRepositoryPort
from src.application.ports.codex_thread_repository_port import CodexThreadRepositoryPort
from src.application.ports.codex_workspace_repository_port import CodexWorkspaceRepositoryPort
from src.core.persistence_contract.unit_of_work_contract import PersistenceSession, UnitOfWork


class CodexControlPort(Protocol):
    """向应用层提供事务和 Codex 仓储工厂。"""

    def create_unit_of_work(self) -> UnitOfWork: ...

    def create_codex_host_repository(
        self,
        session: PersistenceSession,
    ) -> CodexHostRepositoryPort: ...

    def create_codex_workspace_repository(
        self,
        session: PersistenceSession,
    ) -> CodexWorkspaceRepositoryPort: ...

    def create_codex_thread_repository(
        self,
        session: PersistenceSession,
    ) -> CodexThreadRepositoryPort: ...

    def create_codex_operation_repository(
        self,
        session: PersistenceSession,
    ) -> CodexOperationRepositoryPort: ...

    def create_codex_command_outbox_repository(
        self,
        session: PersistenceSession,
    ) -> CodexCommandOutboxRepositoryPort: ...

    def create_codex_approval_repository(
        self,
        session: PersistenceSession,
    ) -> CodexApprovalRepositoryPort: ...

    def create_codex_agent_credential_repository(
        self,
        session: PersistenceSession,
    ) -> CodexAgentCredentialRepositoryPort: ...

    def create_codex_device_key_repository(
        self,
        session: PersistenceSession,
    ) -> CodexDeviceKeyRepositoryPort: ...

    def create_codex_device_authorization_audit_repository(
        self,
        session: PersistenceSession,
    ) -> CodexDeviceAuthorizationAuditRepositoryPort: ...
