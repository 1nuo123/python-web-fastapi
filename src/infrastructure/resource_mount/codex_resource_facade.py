"""Codex 控制面持久化资源门面。"""

from __future__ import annotations

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
from src.core.codex_contract.codex_runtime_contract import CodexRuntimeSettings
from src.core.persistence_contract.unit_of_work_contract import PersistenceSession
from src.infrastructure.persistence.repository_impl.codex_repository_impl import (
    CodexAgentCredentialRepositoryImpl,
    CodexApprovalRepositoryImpl,
    CodexCommandOutboxRepositoryImpl,
    CodexDeviceAuthorizationAuditRepositoryImpl,
    CodexDeviceKeyRepositoryImpl,
    CodexHostRepositoryImpl,
    CodexOperationRepositoryImpl,
    CodexThreadRepositoryImpl,
    CodexWorkspaceRepositoryImpl,
)
from src.infrastructure.resource_mount.shared_resource_lifecycle import SharedResourceLifecycle


class CodexResourceFacade(SharedResourceLifecycle):
    """构造绑定当前 UoW 会话的 Codex 仓储。"""

    def read_codex_runtime_settings(self) -> CodexRuntimeSettings:
        """读取当前生效 Codex 运行时配置。"""

        accessor = self.read_runtime_bundle().codex_accessor
        if accessor is not None:
            return accessor.settings
        return self.read_runtime_bundle().settings.runtime.codex_control

    def create_codex_host_repository(
        self,
        session: PersistenceSession,
    ) -> CodexHostRepositoryPort:
        return CodexHostRepositoryImpl(self._read_sqlalchemy_session(session))

    def create_codex_workspace_repository(
        self,
        session: PersistenceSession,
    ) -> CodexWorkspaceRepositoryPort:
        return CodexWorkspaceRepositoryImpl(self._read_sqlalchemy_session(session))

    def create_codex_thread_repository(
        self,
        session: PersistenceSession,
    ) -> CodexThreadRepositoryPort:
        return CodexThreadRepositoryImpl(self._read_sqlalchemy_session(session))

    def create_codex_operation_repository(
        self,
        session: PersistenceSession,
    ) -> CodexOperationRepositoryPort:
        return CodexOperationRepositoryImpl(self._read_sqlalchemy_session(session))

    def create_codex_command_outbox_repository(
        self,
        session: PersistenceSession,
    ) -> CodexCommandOutboxRepositoryPort:
        return CodexCommandOutboxRepositoryImpl(self._read_sqlalchemy_session(session))

    def create_codex_approval_repository(
        self,
        session: PersistenceSession,
    ) -> CodexApprovalRepositoryPort:
        return CodexApprovalRepositoryImpl(self._read_sqlalchemy_session(session))

    def create_codex_agent_credential_repository(
        self,
        session: PersistenceSession,
    ) -> CodexAgentCredentialRepositoryPort:
        """创建绑定当前 UoW 的 Agent 设备凭据仓储。"""

        return CodexAgentCredentialRepositoryImpl(self._read_sqlalchemy_session(session))

    def create_codex_device_key_repository(
        self,
        session: PersistenceSession,
    ) -> CodexDeviceKeyRepositoryPort:
        """创建设备公钥仓储。"""

        return CodexDeviceKeyRepositoryImpl(self._read_sqlalchemy_session(session))

    def create_codex_device_authorization_audit_repository(
        self,
        session: PersistenceSession,
    ) -> CodexDeviceAuthorizationAuditRepositoryPort:
        """创建设备授权审计仓储。"""

        return CodexDeviceAuthorizationAuditRepositoryImpl(self._read_sqlalchemy_session(session))
