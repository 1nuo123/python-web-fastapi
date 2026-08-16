"""Codex 审批运行时数据修复迁移集成测试。"""

from __future__ import annotations

import json
from typing import TypedDict
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import Connection

from src.cli.run_database_migrations import DatabaseMigrationCli
from src.core.codex_contract.approval_contract import (
    CodexApprovalDisplaySummary,
    CodexApprovalRiskLevel,
    CodexApprovalState,
)
from src.infrastructure.persistence.alembic_runner import (
    ALEMBIC_CONNECT_TIMEOUT_OPTION,
    ALEMBIC_DATABASE_SCHEMA_OPTION,
    ALEMBIC_SCRIPT_LOCATION_OPTION,
    ALEMBIC_SQLALCHEMY_URL_OPTION,
    ALEMBIC_TARGET_REVISION,
)
from src.infrastructure.persistence.sqlalchemy_engine_factory import (
    SqlAlchemyEngineFactory,
)
from src.infrastructure.settings.app_settings_loader import AppSettingsLoader
from src.infrastructure.settings.application_settings import DatabaseRuntimeSettings

ALEMBIC_SCRIPT_LOCATION = "src/infrastructure/persistence/alembic"
PREVIOUS_MIGRATION_REVISION = "202608101100"
APPROVAL_MIGRATION_REVISION = "202608101300"
TEST_OWNER_SUBJECT_ID = "codex-approval-migration-user"
TEST_USERNAME = "codex-approval-migration-user"
TEST_PASSWORD_HASH = "migration-test-password-hash"
TEST_HOST_DISPLAY_NAME = "Codex approval migration host"
TEST_HOST_PLATFORM = "windows"
TEST_HOST_STATUS = "offline"
TEST_THREAD_ID = "codex-approval-migration-thread"
TEST_APPROVAL_KIND = "command"
TEST_PAYLOAD_DIGEST = "a" * 64
TEST_APPROVAL_TITLE = "命令审批"
TEST_APPROVAL_REASON = "Codex请求继续执行。"
TEST_EXPIRED_AT_SQL = "CURRENT_TIMESTAMP - INTERVAL '1 minute'"
EXPECTED_MIGRATED_APPROVAL_VERSION = 2


class LegacyApprovalDisplaySummary(TypedDict):
    """迁移前审批摘要冻结结构。"""

    title: str
    reason: str


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.docker
@pytest.mark.usefixtures("integration_database")
class TestCodexApprovalRuntimeMigrationIntegration:
    """验证旧审批记录升级后的强类型结构和终态。"""

    def test_upgrade_when_approval_uses_legacy_summary_should_backfill_and_expire(
        self,
    ) -> None:
        """旧摘要升级后应可解析，并把过期 pending 记录转为 expired。"""

        DatabaseMigrationCli().execute()
        database_settings = AppSettingsLoader().load().runtime.database
        engine = SqlAlchemyEngineFactory().build(database_settings)
        user_id = uuid4()
        host_id = uuid4()
        approval_id = uuid4()
        try:
            self._run_migration(
                database_settings=database_settings,
                target_revision=PREVIOUS_MIGRATION_REVISION,
                upgrade=False,
            )
            with engine.begin() as connection:
                self._insert_legacy_approval(
                    connection=connection,
                    user_id=user_id,
                    host_id=host_id,
                    approval_id=approval_id,
                )

            self._run_migration(
                database_settings=database_settings,
                target_revision=APPROVAL_MIGRATION_REVISION,
                upgrade=True,
            )

            with engine.connect() as connection:
                migrated = (
                    connection.execute(
                        text(
                            """
                        SELECT display_summary, state, version
                        FROM codex_approval_audit
                        WHERE approval_id = :approval_id
                        """
                        ),
                        {"approval_id": approval_id},
                    )
                    .mappings()
                    .one()
                )

            summary = CodexApprovalDisplaySummary.model_validate(migrated["display_summary"])
            assert summary.title == TEST_APPROVAL_TITLE
            assert summary.reason == TEST_APPROVAL_REASON
            assert summary.risk_level == CodexApprovalRiskLevel.NORMAL
            assert summary.workspace_name is None
            assert summary.command_summary is None
            assert summary.file_scope == ()
            assert summary.permission_names == ()
            assert summary.network_requested is False
            assert summary.extra_root_requested is False
            assert migrated["state"] == CodexApprovalState.EXPIRED.value
            assert migrated["version"] == EXPECTED_MIGRATED_APPROVAL_VERSION
        finally:
            with engine.begin() as connection:
                self._delete_test_rows(
                    connection=connection,
                    approval_id=approval_id,
                    host_id=host_id,
                    user_id=user_id,
                )
            self._run_migration(
                database_settings=database_settings,
                target_revision=ALEMBIC_TARGET_REVISION,
                upgrade=True,
            )
            engine.dispose()

    def _insert_legacy_approval(
        self,
        *,
        connection: Connection,
        user_id: UUID,
        host_id: UUID,
        approval_id: UUID,
    ) -> None:
        """写入满足旧契约的隔离测试数据。"""

        connection.execute(
            text(
                """
                INSERT INTO auth_user (
                    user_id, subject_id, username, password_hash, is_active
                ) VALUES (
                    :user_id, :subject_id, :username, :password_hash, TRUE
                )
                """
            ),
            {
                "user_id": user_id,
                "subject_id": TEST_OWNER_SUBJECT_ID,
                "username": TEST_USERNAME,
                "password_hash": TEST_PASSWORD_HASH,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO codex_host (
                    host_id,
                    owner_subject_id,
                    display_name,
                    platform,
                    status,
                    capabilities,
                    version
                ) VALUES (
                    :host_id,
                    :owner_subject_id,
                    :display_name,
                    :platform,
                    :status,
                    CAST(:capabilities AS jsonb),
                    1
                )
                """
            ),
            {
                "host_id": host_id,
                "owner_subject_id": TEST_OWNER_SUBJECT_ID,
                "display_name": TEST_HOST_DISPLAY_NAME,
                "platform": TEST_HOST_PLATFORM,
                "status": TEST_HOST_STATUS,
                "capabilities": json.dumps({}),
            },
        )
        legacy_summary = LegacyApprovalDisplaySummary(
            title=TEST_APPROVAL_TITLE,
            reason=TEST_APPROVAL_REASON,
        )
        connection.execute(
            text(
                f"""
                INSERT INTO codex_approval_audit (
                    approval_id,
                    owner_subject_id,
                    host_id,
                    thread_id,
                    approval_kind,
                    risk_level,
                    payload_digest,
                    display_summary,
                    state,
                    version,
                    expires_at
                ) VALUES (
                    :approval_id,
                    :owner_subject_id,
                    :host_id,
                    :thread_id,
                    :approval_kind,
                    :risk_level,
                    :payload_digest,
                    CAST(:display_summary AS jsonb),
                    :state,
                    1,
                    {TEST_EXPIRED_AT_SQL}
                )
                """
            ),
            {
                "approval_id": approval_id,
                "owner_subject_id": TEST_OWNER_SUBJECT_ID,
                "host_id": host_id,
                "thread_id": TEST_THREAD_ID,
                "approval_kind": TEST_APPROVAL_KIND,
                "risk_level": CodexApprovalRiskLevel.NORMAL.value,
                "payload_digest": TEST_PAYLOAD_DIGEST,
                "display_summary": json.dumps(legacy_summary, ensure_ascii=False),
                "state": CodexApprovalState.PENDING.value,
            },
        )

    def _delete_test_rows(
        self,
        *,
        connection: Connection,
        approval_id: UUID,
        host_id: UUID,
        user_id: UUID,
    ) -> None:
        """按外键逆序释放迁移测试资源。"""

        connection.execute(
            text("DELETE FROM codex_approval_audit WHERE approval_id = :approval_id"),
            {"approval_id": approval_id},
        )
        connection.execute(
            text("DELETE FROM codex_host WHERE host_id = :host_id"),
            {"host_id": host_id},
        )
        connection.execute(
            text("DELETE FROM auth_user WHERE user_id = :user_id"),
            {"user_id": user_id},
        )

    def _run_migration(
        self,
        *,
        database_settings: DatabaseRuntimeSettings,
        target_revision: str,
        upgrade: bool,
    ) -> None:
        """在隔离测试数据库上执行指定迁移方向。"""

        alembic_config = Config()
        alembic_config.set_main_option(
            ALEMBIC_SCRIPT_LOCATION_OPTION,
            ALEMBIC_SCRIPT_LOCATION,
        )
        alembic_config.set_main_option(
            ALEMBIC_SQLALCHEMY_URL_OPTION,
            database_settings.url,
        )
        alembic_config.set_main_option(
            ALEMBIC_DATABASE_SCHEMA_OPTION,
            database_settings.schema_name,
        )
        alembic_config.set_main_option(
            ALEMBIC_CONNECT_TIMEOUT_OPTION,
            str(database_settings.connect_timeout_seconds),
        )
        if upgrade:
            command.upgrade(alembic_config, target_revision)
            return
        command.downgrade(alembic_config, target_revision)
