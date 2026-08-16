"""为 Codex 控制操作增加强类型派生投影。"""

from __future__ import annotations

from typing import Final

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

REVISION_ID: Final = "202608161230"
DOWN_REVISION_ID: Final = "202608151940"
CODEX_CONTROL_OPERATION_TABLE: Final = "codex_control_operation"
PROJECTION_COLUMN: Final = "projection"

revision = REVISION_ID
down_revision = DOWN_REVISION_ID
branch_labels = None
depends_on = None


class CodexOperationProjectionMigration:
    """增加只保存脱敏派生数据的 operation 投影列。"""

    @staticmethod
    def upgrade() -> None:
        """增加可空 JSONB 投影列，历史 operation 保持无投影。"""

        op.add_column(
            CODEX_CONTROL_OPERATION_TABLE,
            sa.Column(PROJECTION_COLUMN, postgresql.JSONB(), nullable=True),
        )

    @staticmethod
    def downgrade() -> None:
        """删除 operation 投影列。"""

        op.drop_column(CODEX_CONTROL_OPERATION_TABLE, PROJECTION_COLUMN)


upgrade = CodexOperationProjectionMigration.upgrade
downgrade = CodexOperationProjectionMigration.downgrade
