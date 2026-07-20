"""
202605291041 收口身份与任务持久化约束漂移。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

REVISION_ID = "202605291041"
DOWN_REVISION_ID = "202605271330"
AUTH_ROLE_SCOPE_TABLE_NAME = "auth_role_scope"
AUTH_SCOPE_TABLE_NAME = "auth_scope"
AUTH_ROLE_SCOPE_SCOPE_FK_NAME = "fk_auth_role_scope_scope_code_auth_scope"
AUTH_SCOPE_CODE_COLUMN_NAME = "scope_code"
AUTH_SCOPE_NAME_COLUMN_NAME = "scope_name"
AUTH_SCOPE_DESCRIPTION_COLUMN_NAME = "description"
AUTH_SCOPE_KIND_COLUMN_NAME = "scope_kind"
AUTH_SCOPE_ENABLED_COLUMN_NAME = "enabled"
AUTH_SCOPE_MIGRATED_KIND = "builtin"
AUTH_SCOPE_ENABLED_VALUE = True
TASK_EXECUTION_RECORD_TABLE_NAME = "task_execution_record"
TASK_EXECUTION_RECORD_RECORD_ID_COLUMN_NAME = "record_id"
TASK_EXECUTION_RECORD_RECORD_ID_UNIQUE_NAME = "uq_task_execution_record_record_id"
TASK_EXECUTION_RECORD_DUPLICATE_SUFFIX = "-duplicate-"
TASK_EXECUTION_RECORD_DUPLICATE_PREFIX_LENGTH = 100
APP_LOG_RECORD_TABLE_NAME = "app_log_record"
APP_LOG_SCHEMA_VERSION_COLUMN_NAME = "schema_version"
APP_LOG_DETAIL_JSON_COLUMN_NAME = "detail_json"
APP_LOG_SCHEMA_VERSION_CURRENT_LENGTH = 64
APP_LOG_SCHEMA_VERSION_PREVIOUS_LENGTH = 32
POSTGRES_JSONB_CAST_EXPRESSION = "detail_json::jsonb"

revision = REVISION_ID
down_revision = DOWN_REVISION_ID
branch_labels = None
depends_on = None


class Migration:
    """
    身份与任务持久化约束漂移收口迁移。
    """

    def upgrade(self) -> None:
        """
        执行升级。

        :returns: 无返回值。
        :rtype: None
        """

        self._backfill_missing_scope_rows()
        self._normalize_duplicate_task_record_ids()
        op.create_foreign_key(
            AUTH_ROLE_SCOPE_SCOPE_FK_NAME,
            AUTH_ROLE_SCOPE_TABLE_NAME,
            AUTH_SCOPE_TABLE_NAME,
            [AUTH_SCOPE_CODE_COLUMN_NAME],
            [AUTH_SCOPE_CODE_COLUMN_NAME],
            ondelete="RESTRICT",
        )
        op.create_unique_constraint(
            TASK_EXECUTION_RECORD_RECORD_ID_UNIQUE_NAME,
            TASK_EXECUTION_RECORD_TABLE_NAME,
            [TASK_EXECUTION_RECORD_RECORD_ID_COLUMN_NAME],
        )
        self._align_app_log_record_schema()

    def downgrade(self) -> None:
        """
        执行降级。

        :returns: 无返回值。
        :rtype: None
        """

        op.drop_constraint(
            TASK_EXECUTION_RECORD_RECORD_ID_UNIQUE_NAME,
            TASK_EXECUTION_RECORD_TABLE_NAME,
            type_="unique",
        )
        op.drop_constraint(
            AUTH_ROLE_SCOPE_SCOPE_FK_NAME,
            AUTH_ROLE_SCOPE_TABLE_NAME,
            type_="foreignkey",
        )

    def _backfill_missing_scope_rows(self) -> None:
        """
        回填历史角色作用域引用缺失的 scope 目录行。

        :returns: 无返回值。
        :rtype: None
        """

        op.execute(
            sa.text(
                """
                INSERT INTO auth_scope (
                    scope_code,
                    scope_name,
                    description,
                    scope_kind,
                    enabled
                )
                SELECT DISTINCT
                    role_scope.scope_code,
                    role_scope.scope_code,
                    NULL,
                    :scope_kind,
                    :enabled
                FROM auth_role_scope AS role_scope
                LEFT JOIN auth_scope AS scope_catalog
                    ON scope_catalog.scope_code = role_scope.scope_code
                WHERE scope_catalog.scope_code IS NULL
                """
            ).bindparams(
                scope_kind=AUTH_SCOPE_MIGRATED_KIND,
                enabled=AUTH_SCOPE_ENABLED_VALUE,
            )
        )

    def _normalize_duplicate_task_record_ids(self) -> None:
        """
        为历史重复 record_id 增补稳定后缀，避免新增唯一约束失败。

        :returns: 无返回值。
        :rtype: None
        """

        op.execute(
            sa.text(
                """
                WITH duplicate_records AS (
                    SELECT
                        task_execution_record_id,
                        record_id,
                        row_number() OVER (
                            PARTITION BY record_id
                            ORDER BY created_at, task_execution_record_id
                        ) AS duplicate_index
                    FROM task_execution_record
                )
                UPDATE task_execution_record AS target
                SET record_id =
                    left(
                        duplicate_records.record_id,
                        :record_id_prefix_length
                    )
                    || :duplicate_suffix
                    || duplicate_records.duplicate_index::text
                FROM duplicate_records
                WHERE
                    target.task_execution_record_id =
                        duplicate_records.task_execution_record_id
                    AND duplicate_records.duplicate_index > 1
                """
            ).bindparams(
                record_id_prefix_length=TASK_EXECUTION_RECORD_DUPLICATE_PREFIX_LENGTH,
                duplicate_suffix=TASK_EXECUTION_RECORD_DUPLICATE_SUFFIX,
            )
        )

    def _align_app_log_record_schema(self) -> None:
        """
        对齐应用日志表 JSON 与版本字段长度。

        :returns: 无返回值。
        :rtype: None
        """

        op.alter_column(
            APP_LOG_RECORD_TABLE_NAME,
            APP_LOG_SCHEMA_VERSION_COLUMN_NAME,
            type_=sa.String(length=APP_LOG_SCHEMA_VERSION_CURRENT_LENGTH),
            existing_type=sa.String(length=APP_LOG_SCHEMA_VERSION_PREVIOUS_LENGTH),
        )
        op.alter_column(
            APP_LOG_RECORD_TABLE_NAME,
            APP_LOG_DETAIL_JSON_COLUMN_NAME,
            type_=postgresql.JSONB(),
            existing_type=sa.JSON(),
            postgresql_using=POSTGRES_JSONB_CAST_EXPRESSION,
        )


upgrade = Migration().upgrade
downgrade = Migration().downgrade
