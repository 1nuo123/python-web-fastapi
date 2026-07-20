"""
202607021200补齐任务执行记录发布时刻字段迁移模块。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

REVISION_ID = "202607021200"
DOWN_REVISION_ID = "202605291041"
TASK_EXECUTION_RECORD_TABLE_NAME = "task_execution_record"
TASK_EXECUTION_RECORD_PUBLISHED_AT_COLUMN_NAME = "published_at_epoch"
TASK_EXECUTION_OUTBOX_TABLE_NAME = "task_execution_outbox"
TASK_EXECUTION_OUTBOX_MESSAGE_ID_UNIQUE_NAME = "uq_task_execution_outbox_message_id"
TASK_EXECUTION_OUTBOX_STATUS_INDEX_NAME = "ix_task_execution_outbox_status"
TASK_EXECUTION_OUTBOX_JOB_KIND_INDEX_NAME = "ix_task_execution_outbox_job_kind"
TASK_EXECUTION_OUTBOX_DEDUPLICATION_KEY_INDEX_NAME = "ix_task_execution_outbox_deduplication_key"
TASK_EXECUTION_OUTBOX_STATUS_RESERVED = "RESERVED"
MAX_NAME_LENGTH = 128
CURRENT_TIMESTAMP_SQL = sa.text("CURRENT_TIMESTAMP")

revision = REVISION_ID
down_revision = DOWN_REVISION_ID
branch_labels = None
depends_on = None


class Migration:
    """
    迁移封装类型。
    """

    def upgrade(self) -> None:
        """
        执行升级。
        """

        op.add_column(
            TASK_EXECUTION_RECORD_TABLE_NAME,
            sa.Column(
                TASK_EXECUTION_RECORD_PUBLISHED_AT_COLUMN_NAME,
                sa.Integer(),
                nullable=True,
            ),
        )
        op.create_table(
            TASK_EXECUTION_OUTBOX_TABLE_NAME,
            sa.Column(
                "task_execution_outbox_id",
                postgresql.UUID(as_uuid=True),
                nullable=False,
            ),
            sa.Column("message_id", sa.String(length=MAX_NAME_LENGTH), nullable=False),
            sa.Column("job_kind", sa.String(length=MAX_NAME_LENGTH), nullable=False),
            sa.Column(
                "deduplication_key",
                sa.String(length=MAX_NAME_LENGTH),
                nullable=False,
            ),
            sa.Column("backend", sa.String(length=MAX_NAME_LENGTH), nullable=False),
            sa.Column("queue_name", sa.String(length=MAX_NAME_LENGTH), nullable=False),
            sa.Column("payload_kind", sa.String(length=MAX_NAME_LENGTH), nullable=False),
            sa.Column("message_json", sa.Text(), nullable=False),
            sa.Column(
                "status",
                sa.String(length=MAX_NAME_LENGTH),
                nullable=False,
                server_default=TASK_EXECUTION_OUTBOX_STATUS_RESERVED,
            ),
            sa.Column("created_at_epoch", sa.Integer(), nullable=False),
            sa.Column("published_at_epoch", sa.Integer(), nullable=True),
            sa.Column("failed_at_epoch", sa.Integer(), nullable=True),
            sa.Column("failure_reason", sa.Text(), nullable=True),
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
            sa.PrimaryKeyConstraint(
                "task_execution_outbox_id",
                name="pk_task_execution_outbox",
            ),
            sa.UniqueConstraint(
                "message_id",
                name=TASK_EXECUTION_OUTBOX_MESSAGE_ID_UNIQUE_NAME,
            ),
        )
        op.create_index(
            TASK_EXECUTION_OUTBOX_STATUS_INDEX_NAME,
            TASK_EXECUTION_OUTBOX_TABLE_NAME,
            ["status"],
            unique=False,
        )
        op.create_index(
            TASK_EXECUTION_OUTBOX_JOB_KIND_INDEX_NAME,
            TASK_EXECUTION_OUTBOX_TABLE_NAME,
            ["job_kind"],
            unique=False,
        )
        op.create_index(
            TASK_EXECUTION_OUTBOX_DEDUPLICATION_KEY_INDEX_NAME,
            TASK_EXECUTION_OUTBOX_TABLE_NAME,
            ["deduplication_key"],
            unique=False,
        )

    def downgrade(self) -> None:
        """
        执行降级。
        """

        op.drop_index(
            TASK_EXECUTION_OUTBOX_DEDUPLICATION_KEY_INDEX_NAME,
            table_name=TASK_EXECUTION_OUTBOX_TABLE_NAME,
        )
        op.drop_index(
            TASK_EXECUTION_OUTBOX_JOB_KIND_INDEX_NAME,
            table_name=TASK_EXECUTION_OUTBOX_TABLE_NAME,
        )
        op.drop_index(
            TASK_EXECUTION_OUTBOX_STATUS_INDEX_NAME,
            table_name=TASK_EXECUTION_OUTBOX_TABLE_NAME,
        )
        op.drop_table(TASK_EXECUTION_OUTBOX_TABLE_NAME)
        op.drop_column(
            TASK_EXECUTION_RECORD_TABLE_NAME,
            TASK_EXECUTION_RECORD_PUBLISHED_AT_COLUMN_NAME,
        )


upgrade = Migration().upgrade
downgrade = Migration().downgrade
