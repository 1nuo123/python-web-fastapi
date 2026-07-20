"""
202605231821补齐任务执行记录后端字段迁移模块。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

REVISION_ID = "202605231821"
DOWN_REVISION_ID = "202605221609"
TASK_EXECUTION_RECORD_TABLE_NAME = "task_execution_record"
TASK_EXECUTION_RECORD_BACKEND_COLUMN_NAME = "backend"
TASK_EXECUTION_RECORD_BACKEND_INDEX_NAME = "ix_task_execution_record_backend"
LOCAL_TASK_BACKEND_KIND = "local"
MAX_NAME_LENGTH = 128

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
                TASK_EXECUTION_RECORD_BACKEND_COLUMN_NAME,
                sa.String(length=MAX_NAME_LENGTH),
                nullable=False,
                server_default=LOCAL_TASK_BACKEND_KIND,
            ),
        )
        op.create_index(
            TASK_EXECUTION_RECORD_BACKEND_INDEX_NAME,
            TASK_EXECUTION_RECORD_TABLE_NAME,
            [TASK_EXECUTION_RECORD_BACKEND_COLUMN_NAME],
            unique=False,
        )
        op.alter_column(
            TASK_EXECUTION_RECORD_TABLE_NAME,
            TASK_EXECUTION_RECORD_BACKEND_COLUMN_NAME,
            server_default=None,
        )

    def downgrade(self) -> None:
        """
        执行降级。
        """

        op.drop_index(
            TASK_EXECUTION_RECORD_BACKEND_INDEX_NAME,
            table_name=TASK_EXECUTION_RECORD_TABLE_NAME,
        )
        op.drop_column(
            TASK_EXECUTION_RECORD_TABLE_NAME,
            TASK_EXECUTION_RECORD_BACKEND_COLUMN_NAME,
        )


upgrade = Migration().upgrade
downgrade = Migration().downgrade
