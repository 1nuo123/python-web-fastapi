"""规范化 Codex 会话索引中的历史状态。"""

from __future__ import annotations

from typing import Final

import sqlalchemy as sa
from alembic import op

REVISION_ID: Final = "202608151940"
DOWN_REVISION_ID: Final = "202608151820"
CODEX_THREAD_INDEX_TABLE: Final = "codex_thread_index"
STATUS_COLUMN: Final = "status"
UNKNOWN_STATUS: Final = "unknown"
SUPPORTED_STATUS_VALUES: Final = ("idle", "active", "interrupted", "failed", "unknown", "archived")

revision = REVISION_ID
down_revision = DOWN_REVISION_ID
branch_labels = None
depends_on = None


class CodexThreadStatusMigration:
    """将历史 App Server 状态收敛为控制面公开契约允许的状态。"""

    @staticmethod
    def upgrade() -> None:
        """把旧版或未知状态统一写为 ``unknown``。"""

        thread_index_table = sa.table(
            CODEX_THREAD_INDEX_TABLE,
            sa.column(STATUS_COLUMN, sa.String()),
        )
        op.execute(
            thread_index_table.update()
            .where(thread_index_table.c.status.not_in(SUPPORTED_STATUS_VALUES))
            .values(status=UNKNOWN_STATUS)
        )

    @staticmethod
    def downgrade() -> None:
        """状态规范化不可逆，回滚版本不恢复已丢失的旧状态语义。"""


upgrade = CodexThreadStatusMigration.upgrade
downgrade = CodexThreadStatusMigration.downgrade
