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

        supported_status_sql = ", ".join(
            f"'{status_value}'" for status_value in SUPPORTED_STATUS_VALUES
        )
        op.execute(
            sa.text(
                f"UPDATE {CODEX_THREAD_INDEX_TABLE} "
                f"SET {STATUS_COLUMN} = :unknown_status "
                f"WHERE {STATUS_COLUMN} NOT IN ({supported_status_sql})"
            ).bindparams(unknown_status=UNKNOWN_STATUS)
        )

    @staticmethod
    def downgrade() -> None:
        """状态规范化不可逆，回滚版本不恢复已丢失的旧状态语义。"""


upgrade = CodexThreadStatusMigration.upgrade
downgrade = CodexThreadStatusMigration.downgrade
