"""为任务执行 Outbox 增加可恢复投递状态和重试元数据。"""

from __future__ import annotations

from typing import Final

import sqlalchemy as sa
from alembic import op

REVISION_ID: Final = "202609291900"
DOWN_REVISION_ID: Final = "202608190230"
TABLE_NAME: Final = "task_execution_outbox"
DELIVERY_INDEX_NAME: Final = "ix_task_execution_outbox_delivery_due"

revision = REVISION_ID
down_revision = DOWN_REVISION_ID
branch_labels = None
depends_on = None


class TaskExecutionOutboxDeliveryStateMigration:
    """持久化 Outbox 投递尝试、退避和未知结果，保留历史 FAILED 值。"""

    @staticmethod
    def upgrade() -> None:
        op.add_column(
            TABLE_NAME,
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        )
        op.add_column(TABLE_NAME, sa.Column("next_retry_at_epoch", sa.Integer(), nullable=True))
        op.add_column(
            TABLE_NAME,
            sa.Column("last_error_type", sa.String(length=128), nullable=True),
        )
        op.add_column(TABLE_NAME, sa.Column("last_error_message", sa.Text(), nullable=True))
        op.add_column(TABLE_NAME, sa.Column("unknown_at_epoch", sa.Integer(), nullable=True))
        op.add_column(
            TABLE_NAME,
            sa.Column("claim_owner", sa.String(length=128), nullable=True),
        )
        op.add_column(TABLE_NAME, sa.Column("claimed_at_epoch", sa.Integer(), nullable=True))
        op.alter_column(TABLE_NAME, "attempt_count", server_default=None)
        op.create_index(
            DELIVERY_INDEX_NAME,
            TABLE_NAME,
            ["status", "next_retry_at_epoch", "created_at_epoch"],
            unique=False,
        )

    @staticmethod
    def downgrade() -> None:
        op.drop_index(DELIVERY_INDEX_NAME, table_name=TABLE_NAME)
        op.drop_column(TABLE_NAME, "claimed_at_epoch")
        op.drop_column(TABLE_NAME, "claim_owner")
        op.drop_column(TABLE_NAME, "unknown_at_epoch")
        op.drop_column(TABLE_NAME, "last_error_message")
        op.drop_column(TABLE_NAME, "last_error_type")
        op.drop_column(TABLE_NAME, "next_retry_at_epoch")
        op.drop_column(TABLE_NAME, "attempt_count")


upgrade = TaskExecutionOutboxDeliveryStateMigration.upgrade
downgrade = TaskExecutionOutboxDeliveryStateMigration.downgrade
