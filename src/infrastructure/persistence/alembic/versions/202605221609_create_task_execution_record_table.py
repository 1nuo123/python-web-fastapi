"""
202605221609创建任务执行记录表集合基础设施模块。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

REVISION_ID = "202605221609"
TASK_EXECUTION_RECORD_TABLE_NAME = "task_execution_record"
TASK_EXECUTION_RECORD_JOB_KIND_INDEX_NAME = "ix_task_execution_record_job_kind"
TASK_EXECUTION_RECORD_DEDUPLICATION_KEY_INDEX_NAME = "ix_task_execution_record_deduplication_key"
TASK_EXECUTION_RECORD_STATUS_INDEX_NAME = "ix_task_execution_record_status"
TASK_EXECUTION_RECORD_REQUEST_ID_INDEX_NAME = "ix_task_execution_record_request_id"
TASK_EXECUTION_RECORD_TRACE_ID_INDEX_NAME = "ix_task_execution_record_trace_id"
TASK_EXECUTION_RECORD_QUEUE_NAME_INDEX_NAME = "ix_task_execution_record_queue_name"
TASK_EXECUTION_RECORD_UNIQUE_NAME = "uq_task_execution_record_job_kind_deduplication_key"
CURRENT_TIMESTAMP_SQL = sa.text("CURRENT_TIMESTAMP")
MAX_NAME_LENGTH = 128

revision = REVISION_ID
down_revision = "202605181039"
branch_labels = None
depends_on = None


class Migration:
    """
    迁移类型，用于封装当前模块中的相关行为或状态。
    """

    def upgrade(self) -> None:
        """
        处理升级。
        """

        op.create_table(
            TASK_EXECUTION_RECORD_TABLE_NAME,
            sa.Column("task_execution_record_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("record_id", sa.String(length=MAX_NAME_LENGTH), nullable=False),
            sa.Column("task_id", sa.String(length=MAX_NAME_LENGTH), nullable=False),
            sa.Column("job_kind", sa.String(length=MAX_NAME_LENGTH), nullable=False),
            sa.Column("deduplication_key", sa.String(length=MAX_NAME_LENGTH), nullable=False),
            sa.Column("request_id", sa.String(length=MAX_NAME_LENGTH), nullable=False),
            sa.Column("trace_id", sa.String(length=MAX_NAME_LENGTH), nullable=True),
            sa.Column("created_at_epoch", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=MAX_NAME_LENGTH), nullable=False),
            sa.Column("stage", sa.String(length=MAX_NAME_LENGTH), nullable=True),
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("next_retry_at_epoch", sa.Integer(), nullable=True),
            sa.Column("started_at_epoch", sa.Integer(), nullable=True),
            sa.Column("finished_at_epoch", sa.Integer(), nullable=True),
            sa.Column("failed_at_epoch", sa.Integer(), nullable=True),
            sa.Column("last_error_type", sa.String(length=MAX_NAME_LENGTH), nullable=True),
            sa.Column("last_error_message", sa.Text(), nullable=True),
            sa.Column("queue_name", sa.String(length=MAX_NAME_LENGTH), nullable=True),
            sa.Column("payload_kind", sa.String(length=MAX_NAME_LENGTH), nullable=True),
            sa.Column("payload_json", sa.Text(), nullable=True),
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
            sa.PrimaryKeyConstraint("task_execution_record_id", name="pk_task_execution_record"),
            sa.UniqueConstraint(
                "job_kind",
                "deduplication_key",
                name=TASK_EXECUTION_RECORD_UNIQUE_NAME,
            ),
        )
        op.create_index(
            TASK_EXECUTION_RECORD_JOB_KIND_INDEX_NAME,
            TASK_EXECUTION_RECORD_TABLE_NAME,
            ["job_kind"],
            unique=False,
        )
        op.create_index(
            TASK_EXECUTION_RECORD_DEDUPLICATION_KEY_INDEX_NAME,
            TASK_EXECUTION_RECORD_TABLE_NAME,
            ["deduplication_key"],
            unique=False,
        )
        op.create_index(
            TASK_EXECUTION_RECORD_STATUS_INDEX_NAME,
            TASK_EXECUTION_RECORD_TABLE_NAME,
            ["status"],
            unique=False,
        )
        op.create_index(
            TASK_EXECUTION_RECORD_REQUEST_ID_INDEX_NAME,
            TASK_EXECUTION_RECORD_TABLE_NAME,
            ["request_id"],
            unique=False,
        )
        op.create_index(
            TASK_EXECUTION_RECORD_TRACE_ID_INDEX_NAME,
            TASK_EXECUTION_RECORD_TABLE_NAME,
            ["trace_id"],
            unique=False,
        )
        op.create_index(
            TASK_EXECUTION_RECORD_QUEUE_NAME_INDEX_NAME,
            TASK_EXECUTION_RECORD_TABLE_NAME,
            ["queue_name"],
            unique=False,
        )

    def downgrade(self) -> None:
        """
        处理降级。
        """

        op.drop_index(
            TASK_EXECUTION_RECORD_QUEUE_NAME_INDEX_NAME, table_name=TASK_EXECUTION_RECORD_TABLE_NAME
        )
        op.drop_index(
            TASK_EXECUTION_RECORD_TRACE_ID_INDEX_NAME, table_name=TASK_EXECUTION_RECORD_TABLE_NAME
        )
        op.drop_index(
            TASK_EXECUTION_RECORD_REQUEST_ID_INDEX_NAME, table_name=TASK_EXECUTION_RECORD_TABLE_NAME
        )
        op.drop_index(
            TASK_EXECUTION_RECORD_STATUS_INDEX_NAME, table_name=TASK_EXECUTION_RECORD_TABLE_NAME
        )
        op.drop_index(
            TASK_EXECUTION_RECORD_DEDUPLICATION_KEY_INDEX_NAME,
            table_name=TASK_EXECUTION_RECORD_TABLE_NAME,
        )
        op.drop_index(
            TASK_EXECUTION_RECORD_JOB_KIND_INDEX_NAME, table_name=TASK_EXECUTION_RECORD_TABLE_NAME
        )
        op.drop_table(TASK_EXECUTION_RECORD_TABLE_NAME)


upgrade = Migration().upgrade
downgrade = Migration().downgrade
