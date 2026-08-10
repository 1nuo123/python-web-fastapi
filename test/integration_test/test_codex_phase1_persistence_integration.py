"""Codex Phase 1 PostgreSQL 持久化与所有权集成测试。"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from src.infrastructure.persistence.orm_model.auth_user_orm_model import AuthUserOrmModel
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
    def test_migration_when_applied_should_create_codex_tables_and_scopes(
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
            }.issubset(table_names)
            with engine.connect() as connection:
                scope_codes = {
                    row[0] for row in connection.execute(text("SELECT scope_code FROM auth_scope"))
                }
            assert {"codex:read", "codex:operate", "codex:approve"}.issubset(scope_codes)
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
                    ]
                )
                session.commit()
                snapshots = CodexHostRepositoryImpl(session).list_by_owner(owner_subject_id)
                assert [snapshot.host_id for snapshot in snapshots] == [host_id]
                workspace_repository = CodexWorkspaceRepositoryImpl(session)
                assert workspace_repository.list_by_host_and_owner(host_id, other_subject_id) == []
                session.query(CodexWorkspaceOrmModel).filter_by(host_id=host_id).delete()
                session.query(CodexHostOrmModel).filter(
                    CodexHostOrmModel.host_id.in_([host_id, other_host_id])
                ).delete(synchronize_session=False)
                session.query(AuthUserOrmModel).filter(
                    AuthUserOrmModel.subject_id.in_([owner_subject_id, other_subject_id])
                ).delete(synchronize_session=False)
                session.commit()
        finally:
            engine.dispose()
