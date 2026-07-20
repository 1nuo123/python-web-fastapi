"""
202605181039创建应用日志表集合基础设施模块。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

REVISION_ID = "202605181039"
APP_LOG_RECORD_TABLE_NAME = "app_log_record"
APP_LOG_EVENT_KIND_INDEX_NAME = "ix_app_log_record_event_kind"
APP_LOG_OCCURRED_AT_INDEX_NAME = "ix_app_log_record_occurred_at"
APP_LOG_REQUEST_ID_INDEX_NAME = "ix_app_log_record_request_id"
APP_LOG_TRACE_ID_INDEX_NAME = "ix_app_log_record_trace_id"
APP_LOG_LEVEL_INDEX_NAME = "ix_app_log_record_level"
APP_LOG_EVENT_ID_UNIQUE_NAME = "uq_app_log_record_event_id"
CURRENT_TIMESTAMP_SQL = sa.text("CURRENT_TIMESTAMP")
APP_LOG_EVENT_ID_MAX_LENGTH = 128
APP_LOG_SCHEMA_VERSION_MAX_LENGTH = 64
APP_LOG_KIND_MAX_LENGTH = 64
APP_LOG_LEVEL_MAX_LENGTH = 16
APP_LOG_CONTEXT_MAX_LENGTH = 128

revision = REVISION_ID
down_revision = "202605151600"
branch_labels = None
depends_on = None


class Migration:
    """
    迁移类型，用于封装当前模块中的相关行为或状态。
    """

    def upgrade(self) -> None:
        """
        处理升级。

        :returns: 无返回值。
        :rtype: None
        """

        op.create_table(
            APP_LOG_RECORD_TABLE_NAME,
            sa.Column("log_record_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column(
                "event_id",
                sa.String(length=APP_LOG_EVENT_ID_MAX_LENGTH),
                nullable=False,
            ),
            sa.Column(
                "event_kind",
                sa.String(length=APP_LOG_KIND_MAX_LENGTH),
                nullable=False,
            ),
            sa.Column(
                "schema_version",
                sa.String(length=APP_LOG_SCHEMA_VERSION_MAX_LENGTH),
                nullable=False,
            ),
            sa.Column("level", sa.String(length=APP_LOG_LEVEL_MAX_LENGTH), nullable=False),
            sa.Column("message", sa.Text(), nullable=False),
            sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("request_id", sa.String(length=APP_LOG_CONTEXT_MAX_LENGTH), nullable=True),
            sa.Column("trace_id", sa.String(length=APP_LOG_CONTEXT_MAX_LENGTH), nullable=True),
            sa.Column(
                "authenticated_subject_id",
                sa.String(length=APP_LOG_CONTEXT_MAX_LENGTH),
                nullable=True,
            ),
            sa.Column(
                "source_module",
                sa.String(length=APP_LOG_CONTEXT_MAX_LENGTH),
                nullable=False,
            ),
            sa.Column(
                "source_component",
                sa.String(length=APP_LOG_CONTEXT_MAX_LENGTH),
                nullable=False,
            ),
            sa.Column("detail_json", postgresql.JSONB(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=CURRENT_TIMESTAMP_SQL,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=CURRENT_TIMESTAMP_SQL,
            ),
            sa.PrimaryKeyConstraint("log_record_id", name="pk_app_log_record"),
            sa.UniqueConstraint("event_id", name=APP_LOG_EVENT_ID_UNIQUE_NAME),
        )
        op.create_index(
            APP_LOG_OCCURRED_AT_INDEX_NAME,
            APP_LOG_RECORD_TABLE_NAME,
            ["occurred_at"],
            unique=False,
        )
        op.create_index(
            APP_LOG_EVENT_KIND_INDEX_NAME,
            APP_LOG_RECORD_TABLE_NAME,
            ["event_kind"],
            unique=False,
        )
        op.create_index(
            APP_LOG_REQUEST_ID_INDEX_NAME,
            APP_LOG_RECORD_TABLE_NAME,
            ["request_id"],
            unique=False,
        )
        op.create_index(
            APP_LOG_TRACE_ID_INDEX_NAME,
            APP_LOG_RECORD_TABLE_NAME,
            ["trace_id"],
            unique=False,
        )
        op.create_index(
            APP_LOG_LEVEL_INDEX_NAME,
            APP_LOG_RECORD_TABLE_NAME,
            ["level"],
            unique=False,
        )

    def downgrade(self) -> None:
        """
        处理降级。

        :returns: 无返回值。
        :rtype: None
        """

        op.drop_index(APP_LOG_LEVEL_INDEX_NAME, table_name=APP_LOG_RECORD_TABLE_NAME)
        op.drop_index(APP_LOG_TRACE_ID_INDEX_NAME, table_name=APP_LOG_RECORD_TABLE_NAME)
        op.drop_index(APP_LOG_REQUEST_ID_INDEX_NAME, table_name=APP_LOG_RECORD_TABLE_NAME)
        op.drop_index(APP_LOG_EVENT_KIND_INDEX_NAME, table_name=APP_LOG_RECORD_TABLE_NAME)
        op.drop_index(APP_LOG_OCCURRED_AT_INDEX_NAME, table_name=APP_LOG_RECORD_TABLE_NAME)
        op.drop_table(APP_LOG_RECORD_TABLE_NAME)


upgrade = Migration().upgrade
downgrade = Migration().downgrade
