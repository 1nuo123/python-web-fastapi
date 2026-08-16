"""Codex Phase 1 PostgreSQL 持久化与所有权集成测试。"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from src.core.codex_contract.device_key_contract import DeviceKeyState
from src.infrastructure.persistence.orm_model.auth_user_orm_model import AuthUserOrmModel
from src.infrastructure.persistence.orm_model.codex_host_device_key_orm_model import (
    CodexHostDeviceKeyOrmModel,
)
from src.infrastructure.persistence.orm_model.codex_host_orm_model import CodexHostOrmModel
from src.infrastructure.persistence.orm_model.codex_workspace_orm_model import (
    CodexWorkspaceOrmModel,
)
from src.infrastructure.persistence.repository_impl.codex_repository_impl import (
    CodexHostRepositoryImpl,
    CodexWorkspaceRepositoryImpl,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.docker,
    pytest.mark.usefixtures("integration_database"),
]


class TestCodexPhase1PersistenceIntegration:
    def test_migration_when_applied_should_create_scope_model_without_legacy_policy_tables(
        self,
        integration_database: str,
    ) -> None:
        engine = create_engine(integration_database)
        try:
            inspector = inspect(engine)
            table_names = set(inspector.get_table_names())
            assert {
                "codex_host",
                "codex_agent_credential",
                "codex_workspace",
                "codex_thread_index",
                "codex_control_operation",
                "codex_approval_audit",
                "auth_user_scope",
            }.issubset(table_names)
            removed_authorization_tables = {
                "".join(parts)
                for parts in (
                    ("codex_", "permission_", "profile"),
                    ("codex_", "permission_", "profile_", "version"),
                    ("codex_", "user_", "permission_", "assignment"),
                    ("codex_", "host_", "policy_", "state"),
                    ("codex_", "permission_", "audit"),
                )
            }
            assert removed_authorization_tables.isdisjoint(table_names)
            thread_columns = {
                column["name"] for column in inspector.get_columns("codex_thread_index")
            }
            assert {
                "display_name",
                "title_source",
                "model_provider",
                "is_pinned",
                "recency_at",
            }.issubset(thread_columns)
            thread_indexes = {
                index["name"] for index in inspector.get_indexes("codex_thread_index")
            }
            assert {
                "ix_codex_thread_index_workspace_conversation_order",
                "ix_codex_thread_index_owner_conversation_order",
            }.issubset(thread_indexes)
            workspace_columns = {
                column["name"] for column in inspector.get_columns("codex_workspace")
            }
            assert "is_pinned" in workspace_columns
            with engine.connect() as connection:
                scope_codes = {
                    row[0] for row in connection.execute(text("SELECT scope_code FROM auth_scope"))
                }
            assert {
                "codex:read",
                "codex:operate",
                "codex:approve",
                "codex:host_manage",
                "codex:files",
                "codex:terminal",
                "codex:network",
                "codex:full_access",
                "codex:admin_manage",
            }.issubset(scope_codes)
        finally:
            engine.dispose()

    def test_database_should_enforce_owner_immutability_and_active_fingerprint_uniqueness(
        self,
        integration_database: str,
    ) -> None:
        engine = create_engine(integration_database)
        owner_subject_id = f"codex-owner-{uuid4()}"
        other_subject_id = f"codex-other-{uuid4()}"
        first_host_id = uuid4()
        second_host_id = uuid4()
        fingerprint = "f" * 64
        now = datetime.now(UTC)
        try:
            with Session(engine) as session:
                session.add_all(
                    [
                        AuthUserOrmModel(
                            subject_id=owner_subject_id,
                            username=owner_subject_id,
                            password_hash="test",
                            is_active=True,
                        ),
                        AuthUserOrmModel(
                            subject_id=other_subject_id,
                            username=other_subject_id,
                            password_hash="test",
                            is_active=True,
                        ),
                        CodexHostOrmModel(
                            host_id=first_host_id,
                            owner_subject_id=owner_subject_id,
                            display_name="first-host",
                            platform="windows",
                            status="offline",
                            capabilities={},
                            version=1,
                            created_at=now,
                            updated_at=now,
                        ),
                        CodexHostOrmModel(
                            host_id=second_host_id,
                            owner_subject_id=other_subject_id,
                            display_name="second-host",
                            platform="windows",
                            status="offline",
                            capabilities={},
                            version=1,
                            created_at=now,
                            updated_at=now,
                        ),
                    ]
                )
                session.commit()

                with pytest.raises(DBAPIError, match="所有者创建后不可修改"):
                    session.execute(
                        text(
                            "UPDATE codex_host SET owner_subject_id = :owner_subject_id "
                            "WHERE host_id = :host_id"
                        ),
                        {
                            "owner_subject_id": other_subject_id,
                            "host_id": first_host_id,
                        },
                    )
                    session.commit()
                session.rollback()

                session.add(
                    CodexHostDeviceKeyOrmModel(
                        key_id=uuid4(),
                        enrollment_id=uuid4(),
                        host_id=first_host_id,
                        owner_subject_id=owner_subject_id,
                        public_key=b"a" * 32,
                        fingerprint=fingerprint,
                        state=DeviceKeyState.ACTIVE.value,
                        version=1,
                        activated_at=now,
                    )
                )
                session.commit()
                session.add(
                    CodexHostDeviceKeyOrmModel(
                        key_id=uuid4(),
                        enrollment_id=uuid4(),
                        host_id=second_host_id,
                        owner_subject_id=other_subject_id,
                        public_key=b"b" * 32,
                        fingerprint=fingerprint,
                        state=DeviceKeyState.ACTIVE.value,
                        version=1,
                        activated_at=now,
                    )
                )
                with pytest.raises(IntegrityError):
                    session.commit()
                session.rollback()

                session.query(CodexHostDeviceKeyOrmModel).filter_by(fingerprint=fingerprint).delete(
                    synchronize_session=False
                )
                session.query(CodexHostOrmModel).filter(
                    CodexHostOrmModel.host_id.in_([first_host_id, second_host_id])
                ).delete(synchronize_session=False)
                session.query(AuthUserOrmModel).filter(
                    AuthUserOrmModel.subject_id.in_([owner_subject_id, other_subject_id])
                ).delete(synchronize_session=False)
                session.commit()
        finally:
            engine.dispose()

    def test_host_repository_when_listing_should_filter_owner(
        self,
        integration_database: str,
    ) -> None:
        engine = create_engine(integration_database)
        owner_subject_id = f"codex-owner-{uuid4()}"
        other_subject_id = f"codex-other-{uuid4()}"
        host_id = uuid4()
        other_host_id = uuid4()
        revoked_host_id = uuid4()
        revoked_workspace_id = uuid4()
        disabled_workspace_id = uuid4()
        now = datetime.now(UTC)
        try:
            with Session(engine) as session:
                session.add_all(
                    [
                        AuthUserOrmModel(
                            subject_id=owner_subject_id,
                            username=owner_subject_id,
                            password_hash="test",
                            is_active=True,
                        ),
                        AuthUserOrmModel(
                            subject_id=other_subject_id,
                            username=other_subject_id,
                            password_hash="test",
                            is_active=True,
                        ),
                        CodexHostOrmModel(
                            host_id=host_id,
                            owner_subject_id=owner_subject_id,
                            display_name="owner-host",
                            platform="windows",
                            status="offline",
                            capabilities={},
                            version=1,
                            created_at=now,
                            updated_at=now,
                        ),
                        CodexHostOrmModel(
                            host_id=other_host_id,
                            owner_subject_id=other_subject_id,
                            display_name="other-host",
                            platform="windows",
                            status="offline",
                            capabilities={},
                            version=1,
                            created_at=now,
                            updated_at=now,
                        ),
                        CodexHostOrmModel(
                            host_id=revoked_host_id,
                            owner_subject_id=owner_subject_id,
                            display_name="revoked-host",
                            platform="windows",
                            status="revoked",
                            capabilities={},
                            revoked_at=now,
                            version=2,
                            created_at=now,
                            updated_at=now,
                        ),
                        CodexWorkspaceOrmModel(
                            workspace_id=revoked_workspace_id,
                            host_id=revoked_host_id,
                            owner_subject_id=owner_subject_id,
                            agent_workspace_key="revoked-workspace",
                            display_name="Revoked workspace",
                            worktree_policy={},
                            enabled=True,
                            version=1,
                            created_at=now,
                            updated_at=now,
                        ),
                        CodexWorkspaceOrmModel(
                            workspace_id=disabled_workspace_id,
                            host_id=host_id,
                            owner_subject_id=owner_subject_id,
                            agent_workspace_key="disabled-workspace",
                            display_name="Disabled workspace",
                            worktree_policy={},
                            enabled=False,
                            version=2,
                            created_at=now,
                            updated_at=now,
                        ),
                    ]
                )
                session.commit()
                repository = CodexHostRepositoryImpl(session)
                snapshots = repository.list_by_owner(owner_subject_id)
                assert [snapshot.host_id for snapshot in snapshots] == [host_id]
                assert repository.get_by_id_and_owner(revoked_host_id, owner_subject_id) is None
                assert revoked_host_id in {snapshot.host_id for snapshot in repository.list_all()}
                workspace_repository = CodexWorkspaceRepositoryImpl(session)
                assert workspace_repository.list_by_host_and_owner(host_id, other_subject_id) == []
                assert workspace_repository.list_by_host_and_owner(host_id, owner_subject_id) == []
                assert (
                    workspace_repository.get_by_id_and_owner(
                        disabled_workspace_id,
                        owner_subject_id,
                    )
                    is None
                )
                assert (
                    workspace_repository.list_by_host_and_owner(
                        revoked_host_id,
                        owner_subject_id,
                    )
                    == []
                )
                assert (
                    workspace_repository.get_by_id_and_owner(
                        revoked_workspace_id,
                        owner_subject_id,
                    )
                    is None
                )
                session.query(CodexWorkspaceOrmModel).filter(
                    CodexWorkspaceOrmModel.host_id.in_([host_id, revoked_host_id])
                ).delete(synchronize_session=False)
                session.query(CodexHostOrmModel).filter(
                    CodexHostOrmModel.host_id.in_([host_id, other_host_id, revoked_host_id])
                ).delete(synchronize_session=False)
                session.query(AuthUserOrmModel).filter(
                    AuthUserOrmModel.subject_id.in_([owner_subject_id, other_subject_id])
                ).delete(synchronize_session=False)
                session.commit()
        finally:
            engine.dispose()
