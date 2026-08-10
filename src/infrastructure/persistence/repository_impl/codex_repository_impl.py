"""Codex 控制面 SQLAlchemy 仓储实现。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from sqlalchemy import and_, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

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
from src.core.codex_contract.agent_device_auth_contract import (
    AgentDevicePrincipal,
    CodexAgentCredentialIssue,
)
from src.core.codex_contract.approval_contract import CodexApprovalAuditSnapshot
from src.core.codex_contract.command_outbox_contract import (
    CodexCommandOutboxSnapshot,
    CodexCommandOutboxState,
)
from src.core.codex_contract.device_authorization_audit_contract import (
    DeviceAuthorizationAuditSnapshot,
)
from src.core.codex_contract.device_authorization_contract import (
    DeviceAuthorizationDecision,
)
from src.core.codex_contract.device_key_contract import CodexDeviceKeySnapshot, DeviceKeyState
from src.core.codex_contract.host_contract import (
    CodexHostCapabilities,
    CodexHostCompatibilityDetail,
    CodexHostCompatibilityState,
    CodexHostSnapshot,
)
from src.core.codex_contract.operation_contract import CodexControlOperationSnapshot
from src.core.codex_contract.thread_contract import CodexThreadIndexSnapshot
from src.core.codex_contract.workspace_contract import CodexWorkspaceSnapshot
from src.core.cryptography_contract.aead_envelope_contract import (
    AeadAlgorithm,
    AeadEnvelope,
)
from src.core.worktree_contract.worktree_contract import GitWorktreePolicy
from src.infrastructure.persistence.orm_model.codex_agent_credential_orm_model import (
    CodexAgentCredentialOrmModel,
)
from src.infrastructure.persistence.orm_model.codex_approval_audit_orm_model import (
    CodexApprovalAuditOrmModel,
)
from src.infrastructure.persistence.orm_model.codex_command_outbox_orm_model import (
    CodexCommandOutboxOrmModel,
)
from src.infrastructure.persistence.orm_model.codex_control_operation_orm_model import (
    CodexControlOperationOrmModel,
)
from src.infrastructure.persistence.orm_model.codex_device_authorization_audit_orm_model import (
    CodexDeviceAuthorizationAuditOrmModel,
)
from src.infrastructure.persistence.orm_model.codex_host_device_key_orm_model import (
    CodexHostDeviceKeyOrmModel,
)
from src.infrastructure.persistence.orm_model.codex_host_orm_model import CodexHostOrmModel
from src.infrastructure.persistence.orm_model.codex_thread_index_orm_model import (
    CodexThreadIndexOrmModel,
)
from src.infrastructure.persistence.orm_model.codex_workspace_orm_model import (
    CodexWorkspaceOrmModel,
)


class CodexRepositoryDatetimeConverter:
    """集中恢复数据库返回的 UTC 时间。"""

    @staticmethod
    def normalize_required(value: datetime) -> datetime:
        """将数据库时间恢复为 UTC 时区感知时间。"""

        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @classmethod
    def normalize_optional(cls, value: datetime | None) -> datetime | None:
        """将可空数据库时间恢复为 UTC。"""

        return None if value is None else cls.normalize_required(value)


class CodexHostRepositoryImpl(CodexHostRepositoryPort):
    """Codex 主机仓储实现。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def list_by_owner(self, owner_subject_id: str) -> list[CodexHostSnapshot]:
        statement = (
            select(CodexHostOrmModel)
            .where(CodexHostOrmModel.owner_subject_id == owner_subject_id)
            .order_by(CodexHostOrmModel.updated_at.desc())
        )
        return [self._to_snapshot(row) for row in self._session.scalars(statement).all()]

    def get_by_id_and_owner(
        self,
        host_id: UUID,
        owner_subject_id: str,
    ) -> CodexHostSnapshot | None:
        statement = select(CodexHostOrmModel).where(
            CodexHostOrmModel.host_id == host_id,
            CodexHostOrmModel.owner_subject_id == owner_subject_id,
        )
        row = self._session.scalars(statement).one_or_none()
        return None if row is None else self._to_snapshot(row)

    def add(self, snapshot: CodexHostSnapshot) -> None:
        self._session.add(
            CodexHostOrmModel(
                host_id=snapshot.host_id,
                owner_subject_id=snapshot.owner_subject_id,
                display_name=snapshot.display_name,
                platform=snapshot.platform,
                agent_version=snapshot.agent_version,
                codex_version=snapshot.codex_version,
                agent_protocol_version=snapshot.agent_protocol_version,
                app_server_schema_digest=snapshot.app_server_schema_digest,
                status=snapshot.status,
                capabilities=snapshot.capabilities.model_dump(mode="json"),
                compatibility_state=snapshot.compatibility.state.value,
                compatibility_reason_code=snapshot.compatibility.reason_code,
                last_seen_at=snapshot.last_seen_at,
                revoked_at=snapshot.revoked_at,
                created_at=snapshot.created_at,
                updated_at=snapshot.updated_at,
                version=snapshot.version,
            )
        )

    def save(self, snapshot: CodexHostSnapshot) -> None:
        """更新已经存在的主机快照。"""

        self._session.merge(
            CodexHostOrmModel(
                host_id=snapshot.host_id,
                owner_subject_id=snapshot.owner_subject_id,
                display_name=snapshot.display_name,
                platform=snapshot.platform,
                agent_version=snapshot.agent_version,
                codex_version=snapshot.codex_version,
                agent_protocol_version=snapshot.agent_protocol_version,
                app_server_schema_digest=snapshot.app_server_schema_digest,
                status=snapshot.status,
                capabilities=snapshot.capabilities.model_dump(mode="json"),
                compatibility_state=snapshot.compatibility.state.value,
                compatibility_reason_code=snapshot.compatibility.reason_code,
                last_seen_at=snapshot.last_seen_at,
                revoked_at=snapshot.revoked_at,
                created_at=snapshot.created_at,
                updated_at=snapshot.updated_at,
                version=snapshot.version,
            )
        )

    def _to_snapshot(self, row: CodexHostOrmModel) -> CodexHostSnapshot:
        return CodexHostSnapshot(
            host_id=row.host_id,
            owner_subject_id=row.owner_subject_id,
            display_name=row.display_name,
            platform=row.platform,
            agent_version=row.agent_version,
            codex_version=row.codex_version,
            agent_protocol_version=row.agent_protocol_version,
            app_server_schema_digest=row.app_server_schema_digest,
            status=row.status,
            capabilities=CodexHostCapabilities.model_validate(row.capabilities),
            compatibility=CodexHostCompatibilityDetail(
                state=CodexHostCompatibilityState(row.compatibility_state),
                reason_code=row.compatibility_reason_code,
            ),
            last_seen_at=CodexRepositoryDatetimeConverter.normalize_optional(row.last_seen_at),
            revoked_at=CodexRepositoryDatetimeConverter.normalize_optional(row.revoked_at),
            created_at=CodexRepositoryDatetimeConverter.normalize_required(row.created_at),
            updated_at=CodexRepositoryDatetimeConverter.normalize_required(row.updated_at),
            version=row.version,
        )


class CodexAgentCredentialRepositoryImpl(CodexAgentCredentialRepositoryPort):
    """设备凭据摘要与主机所有权联合验证。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def find_active_principal_by_digest(
        self,
        token_digest: str,
    ) -> AgentDevicePrincipal | None:
        statement = (
            select(CodexAgentCredentialOrmModel, CodexHostOrmModel.owner_subject_id)
            .join(
                CodexHostOrmModel,
                CodexHostOrmModel.host_id == CodexAgentCredentialOrmModel.host_id,
            )
            .where(
                CodexAgentCredentialOrmModel.token_digest == token_digest,
                CodexAgentCredentialOrmModel.status == "active",
                CodexAgentCredentialOrmModel.revoked_at.is_(None),
                CodexHostOrmModel.revoked_at.is_(None),
            )
        )
        row = self._session.execute(statement).one_or_none()
        if row is None:
            return None
        credential, owner_subject_id = row
        return AgentDevicePrincipal(
            credential_id=str(credential.credential_id),
            host_id=str(credential.host_id),
            owner_subject_id=str(owner_subject_id),
        )

    def add(self, issue: CodexAgentCredentialIssue) -> None:
        self._session.add(
            CodexAgentCredentialOrmModel(
                credential_id=issue.credential_id,
                host_id=issue.host_id,
                token_digest=issue.token_digest,
                key_id=issue.key_id,
                status=issue.status,
                issued_at=issue.issued_at,
                expires_at=issue.expires_at,
            )
        )

    def rotate(
        self,
        credential_id: UUID,
        issue: CodexAgentCredentialIssue,
        rotated_at: datetime,
    ) -> bool:
        row = self._session.get(CodexAgentCredentialOrmModel, credential_id)
        if row is None or row.status != "active" or row.revoked_at is not None:
            return False
        row.status = "rotated"
        row.rotated_at = rotated_at
        self.add(issue)
        return True

    def revoke(self, credential_id: UUID, revoked_at: datetime) -> bool:
        row = self._session.get(CodexAgentCredentialOrmModel, credential_id)
        if row is None or row.status != "active" or row.revoked_at is not None:
            return False
        row.status = "revoked"
        row.revoked_at = revoked_at
        return True


class CodexDeviceKeyRepositoryImpl(CodexDeviceKeyRepositoryPort):
    """设备公钥仓储实现。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, snapshot: CodexDeviceKeySnapshot) -> None:
        self._session.add(CodexHostDeviceKeyOrmModel(**snapshot.model_dump()))

    def save(self, snapshot: CodexDeviceKeySnapshot) -> None:
        self._session.merge(CodexHostDeviceKeyOrmModel(**snapshot.model_dump()))

    def get_by_key_and_host(
        self,
        key_id: UUID,
        host_id: UUID,
    ) -> CodexDeviceKeySnapshot | None:
        row = self._session.scalars(
            select(CodexHostDeviceKeyOrmModel).where(
                CodexHostDeviceKeyOrmModel.key_id == key_id,
                CodexHostDeviceKeyOrmModel.host_id == host_id,
            )
        ).one_or_none()
        return None if row is None else self._to_snapshot(row)

    def get_by_enrollment(self, enrollment_id: UUID) -> CodexDeviceKeySnapshot | None:
        row = self._session.scalars(
            select(CodexHostDeviceKeyOrmModel).where(
                CodexHostDeviceKeyOrmModel.enrollment_id == enrollment_id
            )
        ).one_or_none()
        return None if row is None else self._to_snapshot(row)

    def list_by_host_and_owner(
        self,
        host_id: UUID,
        owner_subject_id: str,
    ) -> list[CodexDeviceKeySnapshot]:
        rows = self._session.scalars(
            select(CodexHostDeviceKeyOrmModel).where(
                CodexHostDeviceKeyOrmModel.host_id == host_id,
                CodexHostDeviceKeyOrmModel.owner_subject_id == owner_subject_id,
            )
        ).all()
        return [self._to_snapshot(row) for row in rows]

    def list_pending_created_before(
        self,
        *,
        created_before: datetime,
        limit: int,
    ) -> list[CodexDeviceKeySnapshot]:
        """读取达到清理期限的 pending key。"""

        statement = (
            select(CodexHostDeviceKeyOrmModel)
            .where(
                CodexHostDeviceKeyOrmModel.state == DeviceKeyState.PENDING.value,
                CodexHostDeviceKeyOrmModel.created_at <= created_before,
            )
            .order_by(CodexHostDeviceKeyOrmModel.created_at.asc())
            .limit(limit)
        )
        return [self._to_snapshot(row) for row in self._session.scalars(statement).all()]

    def revoke_all_by_host_and_owner(
        self,
        *,
        host_id: UUID,
        owner_subject_id: str,
        revoked_at: datetime,
    ) -> int:
        result = cast(
            CursorResult[tuple[object, ...]],
            self._session.execute(
                update(CodexHostDeviceKeyOrmModel)
                .where(
                    CodexHostDeviceKeyOrmModel.host_id == host_id,
                    CodexHostDeviceKeyOrmModel.owner_subject_id == owner_subject_id,
                    CodexHostDeviceKeyOrmModel.revoked_at.is_(None),
                )
                .values(
                    state=DeviceKeyState.REVOKED.value,
                    revoked_at=revoked_at,
                    updated_at=revoked_at,
                    version=CodexHostDeviceKeyOrmModel.version + 1,
                )
            ),
        )
        return int(result.rowcount or 0)

    def _to_snapshot(self, row: CodexHostDeviceKeyOrmModel) -> CodexDeviceKeySnapshot:
        return CodexDeviceKeySnapshot(
            key_id=row.key_id,
            enrollment_id=row.enrollment_id,
            host_id=row.host_id,
            owner_subject_id=row.owner_subject_id,
            public_key=row.public_key,
            fingerprint=row.fingerprint,
            state=DeviceKeyState(row.state),
            version=row.version,
            activated_at=CodexRepositoryDatetimeConverter.normalize_optional(row.activated_at),
            revoked_at=CodexRepositoryDatetimeConverter.normalize_optional(row.revoked_at),
            retire_after=CodexRepositoryDatetimeConverter.normalize_optional(row.retire_after),
            created_at=CodexRepositoryDatetimeConverter.normalize_required(row.created_at),
            updated_at=CodexRepositoryDatetimeConverter.normalize_required(row.updated_at),
        )


class CodexDeviceAuthorizationAuditRepositoryImpl(CodexDeviceAuthorizationAuditRepositoryPort):
    """设备授权审计仓储实现。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, snapshot: DeviceAuthorizationAuditSnapshot) -> None:
        self._session.add(CodexDeviceAuthorizationAuditOrmModel(**snapshot.model_dump()))

    def get_by_enrollment_and_idempotency_key(
        self,
        *,
        enrollment_id: UUID,
        idempotency_key: str,
    ) -> DeviceAuthorizationAuditSnapshot | None:
        row = self._session.scalars(
            select(CodexDeviceAuthorizationAuditOrmModel).where(
                CodexDeviceAuthorizationAuditOrmModel.enrollment_id == enrollment_id,
                CodexDeviceAuthorizationAuditOrmModel.idempotency_key == idempotency_key,
            )
        ).one_or_none()
        if row is None:
            return None
        return DeviceAuthorizationAuditSnapshot(
            audit_id=row.audit_id,
            enrollment_id=row.enrollment_id,
            host_id=row.host_id,
            owner_subject_id=row.owner_subject_id,
            decision=DeviceAuthorizationDecision(row.decision),
            idempotency_key=row.idempotency_key,
            occurred_at=CodexRepositoryDatetimeConverter.normalize_required(row.occurred_at),
        )


class CodexWorkspaceRepositoryImpl(CodexWorkspaceRepositoryPort):
    """Codex 工作区仓储实现。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def list_by_host_and_owner(
        self,
        host_id: UUID,
        owner_subject_id: str,
    ) -> list[CodexWorkspaceSnapshot]:
        statement = (
            select(CodexWorkspaceOrmModel)
            .where(
                CodexWorkspaceOrmModel.host_id == host_id,
                CodexWorkspaceOrmModel.owner_subject_id == owner_subject_id,
            )
            .order_by(CodexWorkspaceOrmModel.updated_at.desc())
        )
        return [self._to_snapshot(row) for row in self._session.scalars(statement).all()]

    def get_by_id_and_owner(
        self,
        workspace_id: UUID,
        owner_subject_id: str,
    ) -> CodexWorkspaceSnapshot | None:
        statement = select(CodexWorkspaceOrmModel).where(
            CodexWorkspaceOrmModel.workspace_id == workspace_id,
            CodexWorkspaceOrmModel.owner_subject_id == owner_subject_id,
        )
        row = self._session.scalars(statement).one_or_none()
        return None if row is None else self._to_snapshot(row)

    def get_by_agent_key_and_owner(
        self,
        host_id: UUID,
        agent_workspace_key: str,
        owner_subject_id: str,
    ) -> CodexWorkspaceSnapshot | None:
        statement = select(CodexWorkspaceOrmModel).where(
            CodexWorkspaceOrmModel.host_id == host_id,
            CodexWorkspaceOrmModel.agent_workspace_key == agent_workspace_key,
            CodexWorkspaceOrmModel.owner_subject_id == owner_subject_id,
        )
        row = self._session.scalars(statement).one_or_none()
        return None if row is None else self._to_snapshot(row)

    def add(self, snapshot: CodexWorkspaceSnapshot) -> None:
        self._session.add(
            CodexWorkspaceOrmModel(
                workspace_id=snapshot.workspace_id,
                host_id=snapshot.host_id,
                owner_subject_id=snapshot.owner_subject_id,
                agent_workspace_key=snapshot.agent_workspace_key,
                display_name=snapshot.display_name,
                repo_fingerprint=snapshot.repo_fingerprint,
                default_branch=snapshot.default_branch,
                worktree_policy=snapshot.worktree_policy.model_dump(mode="json"),
                enabled=snapshot.enabled,
                created_at=snapshot.created_at,
                updated_at=snapshot.updated_at,
                version=snapshot.version,
            )
        )

    def save(self, snapshot: CodexWorkspaceSnapshot) -> None:
        """更新已经存在的工作区索引。"""

        self._session.merge(
            CodexWorkspaceOrmModel(
                **snapshot.model_dump(exclude={"worktree_policy"}),
                worktree_policy=snapshot.worktree_policy.model_dump(mode="json"),
            )
        )

    def _to_snapshot(self, row: CodexWorkspaceOrmModel) -> CodexWorkspaceSnapshot:
        return CodexWorkspaceSnapshot(
            workspace_id=row.workspace_id,
            host_id=row.host_id,
            owner_subject_id=row.owner_subject_id,
            agent_workspace_key=row.agent_workspace_key,
            display_name=row.display_name,
            repo_fingerprint=row.repo_fingerprint,
            default_branch=row.default_branch,
            worktree_policy=GitWorktreePolicy.model_validate(row.worktree_policy),
            enabled=row.enabled,
            created_at=CodexRepositoryDatetimeConverter.normalize_required(row.created_at),
            updated_at=CodexRepositoryDatetimeConverter.normalize_required(row.updated_at),
            version=row.version,
        )


class CodexThreadRepositoryImpl(CodexThreadRepositoryPort):
    """Codex 线程索引仓储实现。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def list_by_host_and_owner(
        self,
        host_id: UUID,
        owner_subject_id: str,
    ) -> list[CodexThreadIndexSnapshot]:
        statement = (
            select(CodexThreadIndexOrmModel)
            .where(
                CodexThreadIndexOrmModel.host_id == host_id,
                CodexThreadIndexOrmModel.owner_subject_id == owner_subject_id,
            )
            .order_by(CodexThreadIndexOrmModel.updated_at.desc())
        )
        return [self._to_snapshot(row) for row in self._session.scalars(statement).all()]

    def get_by_upstream_id_and_owner(
        self,
        host_id: UUID,
        upstream_thread_id: str,
        owner_subject_id: str,
    ) -> CodexThreadIndexSnapshot | None:
        statement = select(CodexThreadIndexOrmModel).where(
            CodexThreadIndexOrmModel.host_id == host_id,
            CodexThreadIndexOrmModel.upstream_thread_id == upstream_thread_id,
            CodexThreadIndexOrmModel.owner_subject_id == owner_subject_id,
        )
        row = self._session.scalars(statement).one_or_none()
        return None if row is None else self._to_snapshot(row)

    def add(self, snapshot: CodexThreadIndexSnapshot) -> None:
        self._session.add(
            CodexThreadIndexOrmModel(
                thread_index_id=snapshot.thread_index_id,
                host_id=snapshot.host_id,
                workspace_id=snapshot.workspace_id,
                owner_subject_id=snapshot.owner_subject_id,
                upstream_thread_id=snapshot.upstream_thread_id,
                display_name=snapshot.display_name,
                model=snapshot.model,
                reasoning_effort=snapshot.reasoning_effort,
                status=snapshot.status,
                active_turn_id=snapshot.active_turn_id,
                archived=snapshot.archived,
                source_kind=snapshot.source_kind,
                created_at=snapshot.created_at,
                updated_at=snapshot.updated_at,
                last_synced_at=snapshot.last_synced_at,
            )
        )

    def save(self, snapshot: CodexThreadIndexSnapshot) -> None:
        """更新已经存在的线程索引。"""

        self._session.merge(CodexThreadIndexOrmModel(**snapshot.model_dump()))

    def _to_snapshot(self, row: CodexThreadIndexOrmModel) -> CodexThreadIndexSnapshot:
        return CodexThreadIndexSnapshot(
            thread_index_id=row.thread_index_id,
            host_id=row.host_id,
            workspace_id=row.workspace_id,
            owner_subject_id=row.owner_subject_id,
            upstream_thread_id=row.upstream_thread_id,
            display_name=row.display_name,
            model=row.model,
            reasoning_effort=row.reasoning_effort,
            status=row.status,
            active_turn_id=row.active_turn_id,
            archived=row.archived,
            source_kind=row.source_kind,
            created_at=CodexRepositoryDatetimeConverter.normalize_optional(row.created_at),
            updated_at=CodexRepositoryDatetimeConverter.normalize_required(row.updated_at),
            last_synced_at=CodexRepositoryDatetimeConverter.normalize_required(row.last_synced_at),
        )


class CodexOperationRepositoryImpl(CodexOperationRepositoryPort):
    """Codex 控制操作仓储实现。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_actor_and_idempotency_key(
        self,
        actor_subject_id: str,
        idempotency_key: str,
    ) -> CodexControlOperationSnapshot | None:
        statement = select(CodexControlOperationOrmModel).where(
            CodexControlOperationOrmModel.actor_subject_id == actor_subject_id,
            CodexControlOperationOrmModel.idempotency_key == idempotency_key,
        )
        row = self._session.scalars(statement).one_or_none()
        return None if row is None else self._to_snapshot(row)

    def get_by_id_and_owner(
        self,
        operation_id: UUID,
        owner_subject_id: str,
    ) -> CodexControlOperationSnapshot | None:
        statement = select(CodexControlOperationOrmModel).where(
            CodexControlOperationOrmModel.operation_id == operation_id,
            CodexControlOperationOrmModel.owner_subject_id == owner_subject_id,
        )
        row = self._session.scalars(statement).one_or_none()
        return None if row is None else self._to_snapshot(row)

    def get_by_host_and_command_id(
        self,
        host_id: UUID,
        command_id: UUID,
    ) -> CodexControlOperationSnapshot | None:
        statement = select(CodexControlOperationOrmModel).where(
            CodexControlOperationOrmModel.host_id == host_id,
            CodexControlOperationOrmModel.command_id == command_id,
        )
        row = self._session.scalars(statement).one_or_none()
        return None if row is None else self._to_snapshot(row)

    def list_pending_by_host(
        self,
        host_id: UUID,
        statuses: list[str],
    ) -> list[CodexControlOperationSnapshot]:
        statement = select(CodexControlOperationOrmModel).where(
            CodexControlOperationOrmModel.host_id == host_id,
            CodexControlOperationOrmModel.status.in_(statuses),
        )
        return [self._to_snapshot(row) for row in self._session.scalars(statement).all()]

    def add(self, snapshot: CodexControlOperationSnapshot) -> None:
        payload = snapshot.model_dump(exclude={"created_at", "updated_at"})
        self._session.add(
            CodexControlOperationOrmModel(
                **payload,
                created_at=snapshot.created_at,
                updated_at=snapshot.updated_at,
            )
        )

    def save(self, snapshot: CodexControlOperationSnapshot) -> None:
        """更新 operation 恢复状态。"""

        self._session.merge(CodexControlOperationOrmModel(**snapshot.model_dump()))

    def _to_snapshot(
        self,
        row: CodexControlOperationOrmModel,
    ) -> CodexControlOperationSnapshot:
        return CodexControlOperationSnapshot(
            operation_id=row.operation_id,
            command_id=row.command_id,
            actor_subject_id=row.actor_subject_id,
            owner_subject_id=row.owner_subject_id,
            host_id=row.host_id,
            workspace_id=row.workspace_id,
            thread_id=row.thread_id,
            operation_type=row.operation_type,
            idempotency_key=row.idempotency_key,
            request_digest=row.request_digest,
            status=row.status,
            dispatch_attempt=row.dispatch_attempt,
            last_dispatched_at=CodexRepositoryDatetimeConverter.normalize_optional(
                row.last_dispatched_at
            ),
            ack_deadline_at=CodexRepositoryDatetimeConverter.normalize_optional(
                row.ack_deadline_at
            ),
            error_code=row.error_code,
            result_digest=row.result_digest,
            accepted_at=CodexRepositoryDatetimeConverter.normalize_optional(row.accepted_at),
            completed_at=CodexRepositoryDatetimeConverter.normalize_optional(row.completed_at),
            created_at=CodexRepositoryDatetimeConverter.normalize_required(row.created_at),
            updated_at=CodexRepositoryDatetimeConverter.normalize_required(row.updated_at),
        )


class CodexCommandOutboxRepositoryImpl(CodexCommandOutboxRepositoryPort):
    """加密 command outbox 仓储实现。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, snapshot: CodexCommandOutboxSnapshot) -> None:
        self._session.add(self._to_orm(snapshot))

    def save(self, snapshot: CodexCommandOutboxSnapshot) -> None:
        self._session.merge(self._to_orm(snapshot))

    def get_by_command_id(self, command_id: UUID) -> CodexCommandOutboxSnapshot | None:
        row = self._session.scalars(
            select(CodexCommandOutboxOrmModel).where(
                CodexCommandOutboxOrmModel.command_id == command_id
            )
        ).one_or_none()
        return None if row is None else self._to_snapshot(row)

    def claim_ready(
        self,
        *,
        claimed_by: str,
        current_time: datetime,
        stale_before: datetime,
        limit: int,
    ) -> list[CodexCommandOutboxSnapshot]:
        statement = (
            select(CodexCommandOutboxOrmModel)
            .where(
                or_(
                    and_(
                        CodexCommandOutboxOrmModel.state.in_(
                            (
                                CodexCommandOutboxState.PENDING.value,
                                CodexCommandOutboxState.DEFERRED.value,
                                CodexCommandOutboxState.ROUTED.value,
                            )
                        ),
                        CodexCommandOutboxOrmModel.available_at <= current_time,
                    ),
                    and_(
                        CodexCommandOutboxOrmModel.state == CodexCommandOutboxState.CLAIMED.value,
                        CodexCommandOutboxOrmModel.claimed_at <= stale_before,
                    ),
                ),
                CodexCommandOutboxOrmModel.expires_at > current_time,
            )
            .order_by(CodexCommandOutboxOrmModel.available_at.asc())
            .with_for_update(skip_locked=True)
            .limit(limit)
        )
        rows = list(self._session.scalars(statement).all())
        for row in rows:
            row.state = CodexCommandOutboxState.CLAIMED.value
            row.claimed_by = claimed_by
            row.claimed_at = current_time
            row.dispatch_attempt += 1
            row.updated_at = current_time
            row.version += 1
        self._session.flush()
        return [self._to_snapshot(row) for row in rows]

    def claim_by_command_id(
        self,
        *,
        command_id: UUID,
        claimed_by: str,
        current_time: datetime,
    ) -> CodexCommandOutboxSnapshot | None:
        row = self._session.scalars(
            select(CodexCommandOutboxOrmModel)
            .where(
                CodexCommandOutboxOrmModel.command_id == command_id,
                CodexCommandOutboxOrmModel.state.in_(
                    (
                        CodexCommandOutboxState.PENDING.value,
                        CodexCommandOutboxState.DEFERRED.value,
                        CodexCommandOutboxState.ROUTED.value,
                    )
                ),
                or_(
                    CodexCommandOutboxOrmModel.available_at <= current_time,
                    CodexCommandOutboxOrmModel.state == CodexCommandOutboxState.ROUTED.value,
                ),
                CodexCommandOutboxOrmModel.expires_at > current_time,
            )
            .with_for_update(skip_locked=True)
        ).one_or_none()
        if row is None:
            return None
        row.state = CodexCommandOutboxState.CLAIMED.value
        row.claimed_by = claimed_by
        row.claimed_at = current_time
        row.dispatch_attempt += 1
        row.updated_at = current_time
        row.version += 1
        self._session.flush()
        return self._to_snapshot(row)

    def delete_completed_before(self, completed_before: datetime) -> int:
        rows = list(
            self._session.scalars(
                select(CodexCommandOutboxOrmModel)
                .where(
                    CodexCommandOutboxOrmModel.state == CodexCommandOutboxState.COMPLETED.value,
                    CodexCommandOutboxOrmModel.completed_at.is_not(None),
                    CodexCommandOutboxOrmModel.completed_at < completed_before,
                )
                .with_for_update(skip_locked=True)
            ).all()
        )
        for row in rows:
            self._session.delete(row)
        self._session.flush()
        return len(rows)

    def _to_orm(self, snapshot: CodexCommandOutboxSnapshot) -> CodexCommandOutboxOrmModel:
        return CodexCommandOutboxOrmModel(
            outbox_id=snapshot.outbox_id,
            operation_id=snapshot.operation_id,
            command_id=snapshot.command_id,
            host_id=snapshot.host_id,
            owner_subject_id=snapshot.owner_subject_id,
            cipher_algorithm=snapshot.payload.algorithm.value,
            cipher_key_id=snapshot.payload.key_id,
            cipher_nonce=snapshot.payload.nonce,
            ciphertext=snapshot.payload.ciphertext,
            aad_digest=snapshot.payload.aad_digest,
            state=snapshot.state.value,
            route_epoch=snapshot.route_epoch,
            dispatch_attempt=snapshot.dispatch_attempt,
            available_at=snapshot.available_at,
            expires_at=snapshot.expires_at,
            claimed_by=snapshot.claimed_by,
            claimed_at=snapshot.claimed_at,
            accepted_at=snapshot.accepted_at,
            completed_at=snapshot.completed_at,
            last_error_code=snapshot.last_error_code,
            created_at=snapshot.created_at,
            updated_at=snapshot.updated_at,
            version=snapshot.version,
        )

    def _to_snapshot(self, row: CodexCommandOutboxOrmModel) -> CodexCommandOutboxSnapshot:
        return CodexCommandOutboxSnapshot(
            outbox_id=row.outbox_id,
            operation_id=row.operation_id,
            command_id=row.command_id,
            host_id=row.host_id,
            owner_subject_id=row.owner_subject_id,
            payload=AeadEnvelope(
                algorithm=AeadAlgorithm(row.cipher_algorithm),
                key_id=row.cipher_key_id,
                nonce=row.cipher_nonce,
                ciphertext=row.ciphertext,
                aad_digest=row.aad_digest,
            ),
            state=CodexCommandOutboxState(row.state),
            route_epoch=row.route_epoch,
            dispatch_attempt=row.dispatch_attempt,
            available_at=CodexRepositoryDatetimeConverter.normalize_required(row.available_at),
            expires_at=CodexRepositoryDatetimeConverter.normalize_required(row.expires_at),
            claimed_by=row.claimed_by,
            claimed_at=CodexRepositoryDatetimeConverter.normalize_optional(row.claimed_at),
            accepted_at=CodexRepositoryDatetimeConverter.normalize_optional(row.accepted_at),
            completed_at=CodexRepositoryDatetimeConverter.normalize_optional(row.completed_at),
            last_error_code=row.last_error_code,
            created_at=CodexRepositoryDatetimeConverter.normalize_required(row.created_at),
            updated_at=CodexRepositoryDatetimeConverter.normalize_required(row.updated_at),
            version=row.version,
        )


class CodexApprovalRepositoryImpl(CodexApprovalRepositoryPort):
    """Codex 审批审计仓储实现。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def list_by_owner(self, owner_subject_id: str) -> list[CodexApprovalAuditSnapshot]:
        statement = (
            select(CodexApprovalAuditOrmModel)
            .where(CodexApprovalAuditOrmModel.owner_subject_id == owner_subject_id)
            .order_by(CodexApprovalAuditOrmModel.created_at.desc())
        )
        return [self._to_snapshot(row) for row in self._session.scalars(statement).all()]

    def get_by_id_and_owner(
        self,
        approval_id: UUID,
        owner_subject_id: str,
    ) -> CodexApprovalAuditSnapshot | None:
        statement = select(CodexApprovalAuditOrmModel).where(
            CodexApprovalAuditOrmModel.approval_id == approval_id,
            CodexApprovalAuditOrmModel.owner_subject_id == owner_subject_id,
        )
        row = self._session.scalars(statement).one_or_none()
        return None if row is None else self._to_snapshot(row)

    def add(self, snapshot: CodexApprovalAuditSnapshot) -> None:
        payload = snapshot.model_dump(exclude={"created_at", "updated_at"})
        self._session.add(
            CodexApprovalAuditOrmModel(
                **payload,
                created_at=snapshot.created_at,
                updated_at=snapshot.updated_at,
            )
        )

    def save(self, snapshot: CodexApprovalAuditSnapshot) -> None:
        """更新审批交付终态。"""

        self._session.merge(CodexApprovalAuditOrmModel(**snapshot.model_dump()))

    def claim_decision(
        self,
        *,
        approval_id: UUID,
        owner_subject_id: str,
        expected_version: int,
        decided_by: str,
        decision: str,
        decided_at: datetime,
    ) -> CodexApprovalAuditSnapshot | None:
        """通过版本与 pending 状态 CAS 保证多设备只有一次生效。"""

        statement = (
            update(CodexApprovalAuditOrmModel)
            .where(
                CodexApprovalAuditOrmModel.approval_id == approval_id,
                CodexApprovalAuditOrmModel.owner_subject_id == owner_subject_id,
                CodexApprovalAuditOrmModel.state == "pending",
                CodexApprovalAuditOrmModel.version == expected_version,
            )
            .values(
                state="claimed",
                version=expected_version + 1,
                decided_by=decided_by,
                decision=decision,
                decided_at=decided_at,
                updated_at=decided_at,
            )
        )
        result = self._session.execute(statement)
        row_count = cast(int, getattr(result, "rowcount", 0))
        if row_count != 1:
            return None
        return self.get_by_id_and_owner(approval_id, owner_subject_id)

    def _to_snapshot(self, row: CodexApprovalAuditOrmModel) -> CodexApprovalAuditSnapshot:
        return CodexApprovalAuditSnapshot.model_validate(
            {
                "approval_id": row.approval_id,
                "owner_subject_id": row.owner_subject_id,
                "host_id": row.host_id,
                "workspace_id": row.workspace_id,
                "thread_id": row.thread_id,
                "turn_id": row.turn_id,
                "item_id": row.item_id,
                "approval_kind": row.approval_kind,
                "risk_level": row.risk_level,
                "payload_digest": row.payload_digest,
                "display_summary": row.display_summary,
                "state": row.state,
                "version": row.version,
                "expires_at": CodexRepositoryDatetimeConverter.normalize_optional(row.expires_at),
                "decided_by": row.decided_by,
                "decision": row.decision,
                "decided_at": CodexRepositoryDatetimeConverter.normalize_optional(row.decided_at),
                "applied_at": CodexRepositoryDatetimeConverter.normalize_optional(row.applied_at),
                "created_at": CodexRepositoryDatetimeConverter.normalize_required(row.created_at),
                "updated_at": CodexRepositoryDatetimeConverter.normalize_required(row.updated_at),
            }
        )
