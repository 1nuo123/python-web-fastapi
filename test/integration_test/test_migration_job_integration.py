"""
数据库迁移任务集成测试模块。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from pytest import MonkeyPatch
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection, RowMapping
from sqlalchemy.exc import IntegrityError

from src.cli.run_database_migrations import (
    DATABASE_MIGRATION_EXIT_FAILURE,
    DATABASE_MIGRATION_EXIT_SUCCESS,
    MIGRATION_JOB_SCHEMA_VERSION,
    DatabaseMigrationCli,
    MigrationJobStatus,
)
from src.infrastructure.persistence.alembic_runner import (
    ALEMBIC_CONNECT_TIMEOUT_OPTION,
    ALEMBIC_DATABASE_SCHEMA_OPTION,
    ALEMBIC_SCRIPT_LOCATION_OPTION,
    ALEMBIC_SQLALCHEMY_URL_OPTION,
    ALEMBIC_TARGET_REVISION,
    AlembicRunner,
)
from src.infrastructure.persistence.orm_model.app_log_record_orm_model import (
    AppLogRecordOrmModel,
)
from src.infrastructure.persistence.sqlalchemy_engine_factory import (
    SqlAlchemyEngineFactory,
)
from src.infrastructure.settings.app_settings_loader import (
    AppSettingsLoader,
)
from src.infrastructure.settings.application_settings import (
    DatabaseRuntimeSettings,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.usefixtures("integration_database"),
    pytest.mark.docker,
]


COMPOSE_FILE_PATH = Path("compose.yml")
PRODUCTION_COMPOSE_FILE_PATH = Path("compose.production.yml")
DOCKERFILE_PATH = Path("Dockerfile")
ALEMBIC_SCRIPT_LOCATION_PATH = Path("src/infrastructure/persistence/alembic")
IDENTITY_TASK_SCHEMA_DRIFT_DOWN_REVISION = "202605271330"
MIGRATION_SERVICE_NAME = "migration:"
MIGRATION_COMMAND_TEXT = "src.cli.run_database_migrations"
APP_SERVICE_NAME = "app:"
SERVICE_COMPLETED_CONDITION = "service_completed_successfully"
PRODUCTION_ENVIRONMENT_TEXT = "APP_ENV: production"
MIGRATION_RESTART_NO_TEXT = 'restart: "no"'
DOCKER_HEALTHCHECK_TEXT = "HEALTHCHECK"
DOCKER_APP_SETTINGS_LOADER_TEXT = "AppSettingsLoader"
DOCKER_API_PREFIX_TEXT = "runtime.web.api_prefix"
DOCKER_HEALTH_READY_PATH_TEXT = "/health/ready"
DOCKER_THIRD_PARTY_ENTRY_CONFIG_COPY_TEXT = (
    "COPY --chown=app:app funboost_config.py nb_log_config.py ./"
)
MIGRATION_FAILURE_MESSAGE = "迁移失败测试。"
ROLLBACK_PROBE_TABLE_NAME = "migration_failure_rollback_probe"
ROLLBACK_PROBE_CREATE_SQL = (
    "CREATE TABLE migration_failure_rollback_probe (record_id INTEGER NOT NULL)"
)
ROLLBACK_PROBE_FAILURE_SQL = (
    "INSERT INTO migration_failure_rollback_probe (record_id) VALUES (NULL)"
)
ROLLBACK_PROBE_DROP_SQL = "DROP TABLE IF EXISTS migration_failure_rollback_probe"
APP_NOT_STARTED_STATE = "not_started"
APP_RUNNING_STATE = "running"
APP_HEALTHY_STATE = "healthy"
AUTH_ROLE_SCOPE_TABLE_NAME = "auth_role_scope"
AUTH_ROLE_SCOPE_SCOPE_FK_NAME = "fk_auth_role_scope_scope_code_auth_scope"
AUTH_USER_SCOPE_TABLE_NAME = "auth_user_scope"
AUTH_USER_SCOPE_USER_FK_NAME = "fk_auth_user_scope_user_id_auth_user"
AUTH_USER_SCOPE_SCOPE_FK_NAME = "fk_auth_user_scope_scope_code_auth_scope"
AUTH_USER_SCOPE_PRIMARY_KEY_NAME = "pk_auth_user_scope"
AUTH_USER_ID_COLUMN_NAME = "user_id"
AUTH_SCOPE_TABLE_NAME = "auth_scope"
AUTH_SCOPE_CODE_COLUMN_NAME = "scope_code"
AUTH_SCOPE_KIND_COLUMN_NAME = "scope_kind"
AUTH_SCOPE_ENABLED_COLUMN_NAME = "enabled"
AUTH_SCOPE_MIGRATED_KIND = "builtin"
TASK_EXECUTION_RECORD_TABLE_NAME = "task_execution_record"
TASK_EXECUTION_RECORD_RECORD_ID_COLUMN_NAME = "record_id"
TASK_EXECUTION_RECORD_RECORD_ID_UNIQUE_NAME = "uq_task_execution_record_record_id"
TASK_EXECUTION_RECORD_JOB_KIND_COLUMN_NAME = "job_kind"
TASK_EXECUTION_RECORD_DEDUPLICATION_KEY_COLUMN_NAME = "deduplication_key"
TASK_EXECUTION_RECORD_DEDUP_UNIQUE_NAME = "uq_task_execution_record_job_kind_deduplication_key"
APP_LOG_RECORD_TABLE_NAME = "app_log_record"
APP_LOG_DETAIL_JSON_COLUMN_NAME = "detail_json"
APP_LOG_SCHEMA_VERSION_COLUMN_NAME = "schema_version"
APP_LOG_EVENT_ID_COLUMN_NAME = "event_id"
APP_LOG_CREATED_AT_COLUMN_NAME = "created_at"
APP_LOG_UPDATED_AT_COLUMN_NAME = "updated_at"
APP_LOG_JSONB_TYPE_TEXT = "jsonb"
APP_LOG_EVENT_ID_LENGTH = 128
APP_LOG_SCHEMA_VERSION_LENGTH = 64
CONSTRAINED_COLUMNS_FIELD = "constrained_columns"
REFERRED_TABLE_FIELD = "referred_table"
REFERRED_COLUMNS_FIELD = "referred_columns"
NAME_FIELD = "name"
COLUMN_NAMES_FIELD = "column_names"
TYPE_FIELD = "type"
ROLE_ID_BIND_NAME = "role_id"
ROLE_KEY_BIND_NAME = "role_key"
ROLE_NAME_BIND_NAME = "role_name"
SCOPE_CODE_BIND_NAME = "scope_code"
MISSING_SCOPE_ROLE_ID = "00000000-0000-0000-0000-000000001041"
MISSING_SCOPE_ROLE_KEY = "migration_missing_scope_role"
MISSING_SCOPE_ROLE_NAME = "迁移缺失 scope 角色"
MISSING_SCOPE_CODE = "migration:missing:scope"
TASK_RECORD_DUPLICATE_RECORD_ID = "migration-duplicate-record"
TASK_RECORD_FIRST_ID = "00000000-0000-0000-0000-000000291041"
TASK_RECORD_SECOND_ID = "00000000-0000-0000-0000-000000291042"
TASK_RECORD_FIRST_TASK_ID = "migration-task-first"
TASK_RECORD_SECOND_TASK_ID = "migration-task-second"
TASK_RECORD_FIRST_JOB_KIND = "migration_task_first"
TASK_RECORD_SECOND_JOB_KIND = "migration_task_second"
TASK_RECORD_FIRST_DEDUP_KEY = "migration-dedup-first"
TASK_RECORD_SECOND_DEDUP_KEY = "migration-dedup-second"
TASK_RECORD_REQUEST_ID = "migration-request"
TASK_RECORD_CREATED_AT_EPOCH = 1
TASK_RECORD_BACKEND = "local"
TASK_RECORD_STATUS = "PENDING"
TASK_RECORD_STAGE = "dispatch"
TASK_RECORD_ATTEMPT_COUNT = 0
TASK_RECORD_DUPLICATE_SUFFIX = "-duplicate-"
EXPECTED_DIRTY_TASK_RECORD_COUNT = 2
EXPECTED_NORMALIZED_TASK_RECORD_COUNT = 1


class ComposeAppServiceState(StrEnum):
    """
    compose app 服务状态枚举。
    """

    NOT_STARTED = APP_NOT_STARTED_STATE
    RUNNING = APP_RUNNING_STATE
    HEALTHY = APP_HEALTHY_STATE


@dataclass(frozen=True, slots=True)
class ComposeMigrationGate:
    """
    compose 迁移门禁描述。
    """

    condition: str

    def resolve_app_state(self, migration_exit_code: int) -> ComposeAppServiceState:
        """
        根据迁移退出码解析 app 服务状态。
        """

        if (
            self.condition == SERVICE_COMPLETED_CONDITION
            and migration_exit_code != DATABASE_MIGRATION_EXIT_SUCCESS
        ):
            return ComposeAppServiceState.NOT_STARTED
        return ComposeAppServiceState.RUNNING


class TestMigrationJobIntegration:
    """
    数据库迁移任务集成测试集合。
    """

    def test_database_migration_cli_should_upgrade_test_database(self) -> None:
        """
        验证迁移 CLI 可对测试数据库执行升级。
        """

        result = DatabaseMigrationCli().execute()

        assert result.header.schema_version == MIGRATION_JOB_SCHEMA_VERSION
        assert result.detail.status == MigrationJobStatus.SUCCESS
        assert result.detail.exit_code == DATABASE_MIGRATION_EXIT_SUCCESS
        assert DatabaseMigrationCli().run() == DATABASE_MIGRATION_EXIT_SUCCESS

    def test_migration_should_apply_identity_and_task_constraints(self) -> None:
        """
        验证迁移后的数据库约束与 ORM 关键约束保持一致。
        """

        result = DatabaseMigrationCli().execute()
        settings = AppSettingsLoader().load()
        engine = SqlAlchemyEngineFactory().build(settings.runtime.database)
        try:
            inspector = inspect(engine)
            foreign_keys = inspector.get_foreign_keys(
                AUTH_ROLE_SCOPE_TABLE_NAME,
                schema=settings.runtime.database.schema_name,
            )
            user_scope_foreign_keys = inspector.get_foreign_keys(
                AUTH_USER_SCOPE_TABLE_NAME,
                schema=settings.runtime.database.schema_name,
            )
            user_scope_primary_key = inspector.get_pk_constraint(
                AUTH_USER_SCOPE_TABLE_NAME,
                schema=settings.runtime.database.schema_name,
            )
            unique_constraints = inspector.get_unique_constraints(
                TASK_EXECUTION_RECORD_TABLE_NAME,
                schema=settings.runtime.database.schema_name,
            )
            app_log_columns = inspector.get_columns(
                APP_LOG_RECORD_TABLE_NAME,
                schema=settings.runtime.database.schema_name,
            )
        finally:
            engine.dispose()

        role_scope_fk = [
            foreign_key
            for foreign_key in foreign_keys
            if foreign_key[NAME_FIELD] == AUTH_ROLE_SCOPE_SCOPE_FK_NAME
        ]
        user_scope_user_fk = [
            foreign_key
            for foreign_key in user_scope_foreign_keys
            if foreign_key[NAME_FIELD] == AUTH_USER_SCOPE_USER_FK_NAME
        ]
        user_scope_scope_fk = [
            foreign_key
            for foreign_key in user_scope_foreign_keys
            if foreign_key[NAME_FIELD] == AUTH_USER_SCOPE_SCOPE_FK_NAME
        ]
        record_id_unique = [
            constraint
            for constraint in unique_constraints
            if constraint[NAME_FIELD] == TASK_EXECUTION_RECORD_RECORD_ID_UNIQUE_NAME
        ]
        dedup_unique = [
            constraint
            for constraint in unique_constraints
            if constraint[NAME_FIELD] == TASK_EXECUTION_RECORD_DEDUP_UNIQUE_NAME
        ]
        app_log_column_by_name = {column[NAME_FIELD]: column for column in app_log_columns}

        assert result.detail.status == MigrationJobStatus.SUCCESS
        assert role_scope_fk
        assert role_scope_fk[0][CONSTRAINED_COLUMNS_FIELD] == [AUTH_SCOPE_CODE_COLUMN_NAME]
        assert role_scope_fk[0][REFERRED_TABLE_FIELD] == AUTH_SCOPE_TABLE_NAME
        assert role_scope_fk[0][REFERRED_COLUMNS_FIELD] == [AUTH_SCOPE_CODE_COLUMN_NAME]
        assert user_scope_user_fk
        assert user_scope_user_fk[0][CONSTRAINED_COLUMNS_FIELD] == [AUTH_USER_ID_COLUMN_NAME]
        assert user_scope_user_fk[0][REFERRED_TABLE_FIELD] == "auth_user"
        assert user_scope_scope_fk
        assert user_scope_scope_fk[0][CONSTRAINED_COLUMNS_FIELD] == [AUTH_SCOPE_CODE_COLUMN_NAME]
        assert user_scope_scope_fk[0][REFERRED_TABLE_FIELD] == AUTH_SCOPE_TABLE_NAME
        assert user_scope_primary_key[NAME_FIELD] == AUTH_USER_SCOPE_PRIMARY_KEY_NAME
        assert user_scope_primary_key[CONSTRAINED_COLUMNS_FIELD] == [
            AUTH_USER_ID_COLUMN_NAME,
            AUTH_SCOPE_CODE_COLUMN_NAME,
        ]
        assert record_id_unique
        assert record_id_unique[0][COLUMN_NAMES_FIELD] == [
            TASK_EXECUTION_RECORD_RECORD_ID_COLUMN_NAME
        ]
        assert dedup_unique
        assert dedup_unique[0][COLUMN_NAMES_FIELD] == [
            TASK_EXECUTION_RECORD_JOB_KIND_COLUMN_NAME,
            TASK_EXECUTION_RECORD_DEDUPLICATION_KEY_COLUMN_NAME,
        ]
        assert (
            str(app_log_column_by_name[APP_LOG_DETAIL_JSON_COLUMN_NAME][TYPE_FIELD])
            .lower()
            .startswith(APP_LOG_JSONB_TYPE_TEXT)
        )
        assert (
            app_log_column_by_name[APP_LOG_EVENT_ID_COLUMN_NAME][TYPE_FIELD].length
            == APP_LOG_EVENT_ID_LENGTH
        )
        assert (
            app_log_column_by_name[APP_LOG_SCHEMA_VERSION_COLUMN_NAME][TYPE_FIELD].length
            == APP_LOG_SCHEMA_VERSION_LENGTH
        )
        assert APP_LOG_CREATED_AT_COLUMN_NAME in app_log_column_by_name
        assert APP_LOG_UPDATED_AT_COLUMN_NAME in app_log_column_by_name
        assert APP_LOG_CREATED_AT_COLUMN_NAME in AppLogRecordOrmModel.__table__.columns
        assert APP_LOG_UPDATED_AT_COLUMN_NAME in AppLogRecordOrmModel.__table__.columns

    def test_migration_should_backfill_dirty_legacy_scope_and_normalize_record_id(
        self,
    ) -> None:
        """
        验证旧 revision 脏数据升级时会回填缺失 scope 并清理重复 record_id。

        :returns: 无返回值。
        :rtype: None
        """

        DatabaseMigrationCli().execute()
        settings = AppSettingsLoader().load()
        database_settings = settings.runtime.database
        engine = SqlAlchemyEngineFactory().build(database_settings)
        try:
            self._run_alembic_downgrade(
                database_settings=database_settings,
                target_revision=IDENTITY_TASK_SCHEMA_DRIFT_DOWN_REVISION,
            )
            with engine.begin() as connection:
                self._cleanup_dirty_legacy_rows(connection)
                self._insert_dirty_legacy_scope_reference(connection)
                self._insert_task_execution_record(
                    connection=connection,
                    task_execution_record_id=TASK_RECORD_FIRST_ID,
                    task_id=TASK_RECORD_FIRST_TASK_ID,
                    job_kind=TASK_RECORD_FIRST_JOB_KIND,
                    deduplication_key=TASK_RECORD_FIRST_DEDUP_KEY,
                )
                self._insert_task_execution_record(
                    connection=connection,
                    task_execution_record_id=TASK_RECORD_SECOND_ID,
                    task_id=TASK_RECORD_SECOND_TASK_ID,
                    job_kind=TASK_RECORD_SECOND_JOB_KIND,
                    deduplication_key=TASK_RECORD_SECOND_DEDUP_KEY,
                )

            self._run_alembic_upgrade(
                database_settings=database_settings,
                target_revision=ALEMBIC_TARGET_REVISION,
            )

            with engine.connect() as connection:
                scope_row = self._read_backfilled_scope(connection)
                record_ids = self._read_dirty_task_record_ids(connection)

            normalized_record_ids = [
                record_id
                for record_id in record_ids
                if record_id != TASK_RECORD_DUPLICATE_RECORD_ID
            ]

            assert scope_row is not None
            assert scope_row[AUTH_SCOPE_CODE_COLUMN_NAME] == MISSING_SCOPE_CODE
            assert scope_row[AUTH_SCOPE_KIND_COLUMN_NAME] == AUTH_SCOPE_MIGRATED_KIND
            assert scope_row[AUTH_SCOPE_ENABLED_COLUMN_NAME] is True
            assert len(record_ids) == EXPECTED_DIRTY_TASK_RECORD_COUNT
            assert TASK_RECORD_DUPLICATE_RECORD_ID in record_ids
            assert len(normalized_record_ids) == EXPECTED_NORMALIZED_TASK_RECORD_COUNT
            normalized_record_id = next(iter(normalized_record_ids))
            assert normalized_record_id.startswith(
                f"{TASK_RECORD_DUPLICATE_RECORD_ID}{TASK_RECORD_DUPLICATE_SUFFIX}"
            )
        finally:
            with engine.begin() as connection:
                self._cleanup_dirty_legacy_rows(connection)
            self._run_alembic_upgrade(
                database_settings=database_settings,
                target_revision=ALEMBIC_TARGET_REVISION,
            )
            engine.dispose()

    def test_task_record_id_unique_constraint_should_reject_duplicates(
        self,
    ) -> None:
        """
        验证迁移后的任务执行记录 record_id 唯一约束真实生效。
        """

        DatabaseMigrationCli().execute()
        settings = AppSettingsLoader().load()
        engine = SqlAlchemyEngineFactory().build(settings.runtime.database)
        raised_error: IntegrityError | None = None
        try:
            with engine.connect() as connection:
                transaction = connection.begin()
                try:
                    self._insert_task_execution_record(
                        connection=connection,
                        task_execution_record_id=TASK_RECORD_FIRST_ID,
                        task_id=TASK_RECORD_FIRST_TASK_ID,
                        job_kind=TASK_RECORD_FIRST_JOB_KIND,
                        deduplication_key=TASK_RECORD_FIRST_DEDUP_KEY,
                    )
                    self._insert_task_execution_record(
                        connection=connection,
                        task_execution_record_id=TASK_RECORD_SECOND_ID,
                        task_id=TASK_RECORD_SECOND_TASK_ID,
                        job_kind=TASK_RECORD_SECOND_JOB_KIND,
                        deduplication_key=TASK_RECORD_SECOND_DEDUP_KEY,
                    )
                except IntegrityError as exc:
                    raised_error = exc
                finally:
                    transaction.rollback()
        finally:
            engine.dispose()

        assert raised_error is not None

    def test_auth_role_scope_should_reject_missing_scope_after_migration(
        self,
    ) -> None:
        """
        验证迁移后 auth_role_scope 不能引用不存在的 scope。
        """

        DatabaseMigrationCli().execute()
        settings = AppSettingsLoader().load()
        engine = SqlAlchemyEngineFactory().build(settings.runtime.database)
        raised_error: IntegrityError | None = None
        try:
            with engine.connect() as connection:
                transaction = connection.begin()
                try:
                    connection.execute(
                        text(
                            """
                            INSERT INTO auth_role (
                                role_id,
                                role_key,
                                role_name
                            )
                            VALUES (
                                :role_id,
                                :role_key,
                                :role_name
                            )
                            ON CONFLICT (role_key) DO NOTHING
                            """
                        ),
                        {
                            ROLE_ID_BIND_NAME: MISSING_SCOPE_ROLE_ID,
                            ROLE_KEY_BIND_NAME: MISSING_SCOPE_ROLE_KEY,
                            ROLE_NAME_BIND_NAME: MISSING_SCOPE_ROLE_NAME,
                        },
                    )
                    connection.execute(
                        text(
                            """
                            INSERT INTO auth_role_scope (
                                role_id,
                                scope_code
                            )
                            VALUES (
                                :role_id,
                                :scope_code
                            )
                            """
                        ),
                        {
                            ROLE_ID_BIND_NAME: MISSING_SCOPE_ROLE_ID,
                            SCOPE_CODE_BIND_NAME: MISSING_SCOPE_CODE,
                        },
                    )
                except IntegrityError as exc:
                    raised_error = exc
                finally:
                    transaction.rollback()
        finally:
            engine.dispose()

        assert raised_error is not None

    def test_database_migration_cli_when_upgrade_failed_should_return_failure(
        self,
        monkeypatch: MonkeyPatch,
    ) -> None:
        """
        验证迁移失败时 CLI 返回失败结果。
        """

        def raise_migration_failure(
            runner: AlembicRunner,
            database_settings: object,
        ) -> None:
            raise RuntimeError(MIGRATION_FAILURE_MESSAGE)

        monkeypatch.setattr(
            AlembicRunner,
            "upgrade_head",
            raise_migration_failure,
        )

        result = DatabaseMigrationCli().execute()

        assert result.detail.status == MigrationJobStatus.FAILED
        assert result.detail.exit_code == DATABASE_MIGRATION_EXIT_FAILURE

    def test_migration_when_midway_statement_failed_should_rollback_database_state(
        self,
        integration_database: str,
    ) -> None:
        """验证真实 PostgreSQL DDL 中途失败会回滚此前迁移步骤。"""

        settings = (
            AppSettingsLoader()
            .load()
            .runtime.database.model_copy(update={"url": integration_database})
        )
        engine = SqlAlchemyEngineFactory().build(settings)
        try:
            with engine.connect() as connection:
                connection.execute(text(ROLLBACK_PROBE_DROP_SQL))
                connection.commit()
                transaction = connection.begin()
                try:
                    connection.execute(text(ROLLBACK_PROBE_CREATE_SQL))
                    connection.execute(text(ROLLBACK_PROBE_FAILURE_SQL))
                except IntegrityError:
                    transaction.rollback()
                else:
                    transaction.commit()
                    pytest.fail("迁移失败探针没有触发数据库约束错误。")

            assert inspect(engine).has_table(ROLLBACK_PROBE_TABLE_NAME) is False
        finally:
            with engine.begin() as cleanup_connection:
                cleanup_connection.execute(text(ROLLBACK_PROBE_DROP_SQL))
            engine.dispose()

    def test_compose_should_gate_app_by_migration_job(self) -> None:
        """
        验证 compose 中 app 依赖 migration 成功完成。
        """

        compose_text = COMPOSE_FILE_PATH.read_text(encoding="utf-8")

        assert MIGRATION_SERVICE_NAME in compose_text
        assert MIGRATION_COMMAND_TEXT in compose_text
        assert MIGRATION_RESTART_NO_TEXT in compose_text
        assert APP_SERVICE_NAME in compose_text
        assert SERVICE_COMPLETED_CONDITION in compose_text

    def test_dockerfile_healthcheck_should_use_runtime_api_prefix(self) -> None:
        """
        验证 Docker 健康检查从运行时配置读取 API 前缀。
        """

        dockerfile_text = DOCKERFILE_PATH.read_text(encoding="utf-8")

        assert DOCKER_HEALTHCHECK_TEXT in dockerfile_text
        assert DOCKER_APP_SETTINGS_LOADER_TEXT in dockerfile_text
        assert DOCKER_API_PREFIX_TEXT in dockerfile_text
        assert DOCKER_HEALTH_READY_PATH_TEXT in dockerfile_text

    def test_dockerfile_should_include_third_party_entry_configs(self) -> None:
        """验证只读生产镜像包含第三方日志与任务入口配置。"""

        dockerfile_text = DOCKERFILE_PATH.read_text(encoding="utf-8")

        assert DOCKER_THIRD_PARTY_ENTRY_CONFIG_COPY_TEXT in dockerfile_text

    def test_compose_gate_when_migration_failed_should_not_start_app(self) -> None:
        """
        验证迁移非 0 退出时 compose 门禁不让 app 进入服务态。
        """

        compose_text = COMPOSE_FILE_PATH.read_text(encoding="utf-8")
        gate = ComposeMigrationGate(condition=SERVICE_COMPLETED_CONDITION)

        failed_state = gate.resolve_app_state(DATABASE_MIGRATION_EXIT_FAILURE)
        success_state = gate.resolve_app_state(DATABASE_MIGRATION_EXIT_SUCCESS)

        assert SERVICE_COMPLETED_CONDITION in compose_text
        assert failed_state == ComposeAppServiceState.NOT_STARTED
        assert failed_state != ComposeAppServiceState.RUNNING
        assert failed_state != ComposeAppServiceState.HEALTHY
        assert success_state == ComposeAppServiceState.RUNNING

    def test_production_compose_should_use_production_migration_environment(
        self,
    ) -> None:
        """
        验证生产 compose 覆盖 migration 生产环境。
        """

        compose_text = PRODUCTION_COMPOSE_FILE_PATH.read_text(encoding="utf-8")

        assert MIGRATION_SERVICE_NAME in compose_text
        assert PRODUCTION_ENVIRONMENT_TEXT in compose_text

    def _run_alembic_upgrade(
        self,
        *,
        database_settings: DatabaseRuntimeSettings,
        target_revision: str,
    ) -> None:
        """
        执行指定 revision 的 Alembic 升级。

        :param database_settings: 数据库运行时配置。
        :type database_settings: DatabaseRuntimeSettings
        :param target_revision: 目标 Alembic revision。
        :type target_revision: str
        :returns: 无返回值。
        :rtype: None
        """

        command.upgrade(
            self._build_alembic_config(database_settings),
            target_revision,
        )

    def _run_alembic_downgrade(
        self,
        *,
        database_settings: DatabaseRuntimeSettings,
        target_revision: str,
    ) -> None:
        """
        执行指定 revision 的 Alembic 降级。

        :param database_settings: 数据库运行时配置。
        :type database_settings: DatabaseRuntimeSettings
        :param target_revision: 目标 Alembic revision。
        :type target_revision: str
        :returns: 无返回值。
        :rtype: None
        """

        command.downgrade(
            self._build_alembic_config(database_settings),
            target_revision,
        )

    def _build_alembic_config(
        self,
        database_settings: DatabaseRuntimeSettings,
    ) -> Config:
        """
        构建迁移测试使用的 Alembic 配置。

        :param database_settings: 数据库运行时配置。
        :type database_settings: DatabaseRuntimeSettings
        :returns: Alembic 配置对象。
        :rtype: Config
        """

        alembic_config = Config()
        alembic_config.set_main_option(
            ALEMBIC_SCRIPT_LOCATION_OPTION,
            str(ALEMBIC_SCRIPT_LOCATION_PATH),
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
        return alembic_config

    def _insert_dirty_legacy_scope_reference(
        self,
        connection: Connection,
    ) -> None:
        """
        写入旧 revision 允许存在的缺失 scope 引用。

        :param connection: SQLAlchemy 数据库连接。
        :type connection: Connection
        :returns: 无返回值。
        :rtype: None
        """

        connection.execute(
            text(
                """
                INSERT INTO auth_role (
                    role_id,
                    role_key,
                    role_name
                )
                VALUES (
                    :role_id,
                    :role_key,
                    :role_name
                )
                """
            ),
            {
                ROLE_ID_BIND_NAME: MISSING_SCOPE_ROLE_ID,
                ROLE_KEY_BIND_NAME: MISSING_SCOPE_ROLE_KEY,
                ROLE_NAME_BIND_NAME: MISSING_SCOPE_ROLE_NAME,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO auth_role_scope (
                    role_id,
                    scope_code
                )
                VALUES (
                    :role_id,
                    :scope_code
                )
                """
            ),
            {
                ROLE_ID_BIND_NAME: MISSING_SCOPE_ROLE_ID,
                SCOPE_CODE_BIND_NAME: MISSING_SCOPE_CODE,
            },
        )

    def _cleanup_dirty_legacy_rows(self, connection: Connection) -> None:
        """
        清理迁移脏数据测试写入的资源。

        :param connection: SQLAlchemy 数据库连接。
        :type connection: Connection
        :returns: 无返回值。
        :rtype: None
        """

        connection.execute(
            text(
                """
                DELETE FROM task_execution_record
                WHERE task_execution_record_id IN (
                    :first_task_execution_record_id,
                    :second_task_execution_record_id
                )
                """
            ),
            {
                "first_task_execution_record_id": TASK_RECORD_FIRST_ID,
                "second_task_execution_record_id": TASK_RECORD_SECOND_ID,
            },
        )
        connection.execute(
            text(
                """
                DELETE FROM auth_role_scope
                WHERE role_id = :role_id
                    OR scope_code = :scope_code
                """
            ),
            {
                ROLE_ID_BIND_NAME: MISSING_SCOPE_ROLE_ID,
                SCOPE_CODE_BIND_NAME: MISSING_SCOPE_CODE,
            },
        )
        connection.execute(
            text(
                """
                DELETE FROM auth_scope
                WHERE scope_code = :scope_code
                """
            ),
            {SCOPE_CODE_BIND_NAME: MISSING_SCOPE_CODE},
        )
        connection.execute(
            text(
                """
                DELETE FROM auth_role
                WHERE role_id = :role_id
                    OR role_key = :role_key
                """
            ),
            {
                ROLE_ID_BIND_NAME: MISSING_SCOPE_ROLE_ID,
                ROLE_KEY_BIND_NAME: MISSING_SCOPE_ROLE_KEY,
            },
        )

    def _read_backfilled_scope(
        self,
        connection: Connection,
    ) -> RowMapping | None:
        """
        读取迁移回填的 scope 目录行。

        :param connection: SQLAlchemy 数据库连接。
        :type connection: Connection
        :returns: scope 目录行；不存在时返回空值。
        :rtype: RowMapping | None
        """

        return (
            connection.execute(
                text(
                    """
                    SELECT
                        scope_code,
                        scope_kind,
                        enabled
                    FROM auth_scope
                    WHERE scope_code = :scope_code
                    """
                ),
                {SCOPE_CODE_BIND_NAME: MISSING_SCOPE_CODE},
            )
            .mappings()
            .one_or_none()
        )

    def _read_dirty_task_record_ids(self, connection: Connection) -> list[str]:
        """
        读取迁移清理后的任务执行记录 record_id。

        :param connection: SQLAlchemy 数据库连接。
        :type connection: Connection
        :returns: 任务执行记录 record_id 列表。
        :rtype: list[str]
        """

        rows = (
            connection.execute(
                text(
                    """
                    SELECT record_id
                    FROM task_execution_record
                    WHERE task_execution_record_id IN (
                        :first_task_execution_record_id,
                        :second_task_execution_record_id
                    )
                    ORDER BY record_id
                    """
                ),
                {
                    "first_task_execution_record_id": TASK_RECORD_FIRST_ID,
                    "second_task_execution_record_id": TASK_RECORD_SECOND_ID,
                },
            )
            .mappings()
            .all()
        )
        return [str(row[TASK_EXECUTION_RECORD_RECORD_ID_COLUMN_NAME]) for row in rows]

    def _insert_task_execution_record(
        self,
        *,
        connection: Connection,
        task_execution_record_id: str,
        task_id: str,
        job_kind: str,
        deduplication_key: str,
    ) -> None:
        """
        插入任务执行记录唯一约束测试数据。
        """

        connection.execute(
            text(
                """
                INSERT INTO task_execution_record (
                    task_execution_record_id,
                    record_id,
                    task_id,
                    job_kind,
                    deduplication_key,
                    request_id,
                    created_at_epoch,
                    backend,
                    status,
                    stage,
                    attempt_count
                )
                VALUES (
                    :task_execution_record_id,
                    :record_id,
                    :task_id,
                    :job_kind,
                    :deduplication_key,
                    :request_id,
                    :created_at_epoch,
                    :backend,
                    :status,
                    :stage,
                    :attempt_count
                )
                """
            ),
            {
                "task_execution_record_id": task_execution_record_id,
                "record_id": TASK_RECORD_DUPLICATE_RECORD_ID,
                "task_id": task_id,
                "job_kind": job_kind,
                "deduplication_key": deduplication_key,
                "request_id": TASK_RECORD_REQUEST_ID,
                "created_at_epoch": TASK_RECORD_CREATED_AT_EPOCH,
                "backend": TASK_RECORD_BACKEND,
                "status": TASK_RECORD_STATUS,
                "stage": TASK_RECORD_STAGE,
                "attempt_count": TASK_RECORD_ATTEMPT_COUNT,
            },
        )
