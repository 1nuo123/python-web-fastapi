"""为 Codex 会话索引增加不含正文的 turn 运行态。"""

from __future__ import annotations

from typing import Final

import sqlalchemy as sa
from alembic import op

REVISION_ID: Final = "202608190130"
DOWN_REVISION_ID: Final = "202608161230"
CODEX_THREAD_INDEX_TABLE: Final = "codex_thread_index"

revision = REVISION_ID
down_revision = DOWN_REVISION_ID
branch_labels = None
depends_on = None


class CodexTurnRuntimeMigration:
    """持久化服务端阶段、活动时间和 fenced lease 代次。"""

    @staticmethod
    def upgrade() -> None:
        """增加元数据列，并以零代次表示没有已认领运行态的历史线程。"""

        op.add_column(
            CODEX_THREAD_INDEX_TABLE,
            sa.Column("runtime_turn_id", sa.String(length=256), nullable=True),
        )
        op.add_column(
            CODEX_THREAD_INDEX_TABLE,
            sa.Column("phase", sa.String(length=32), nullable=True),
        )
        op.add_column(
            CODEX_THREAD_INDEX_TABLE,
            sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.add_column(
            CODEX_THREAD_INDEX_TABLE,
            sa.Column("stalled_reason", sa.String(length=512), nullable=True),
        )
        op.add_column(
            CODEX_THREAD_INDEX_TABLE,
            sa.Column(
                "lease_generation",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )
        op.add_column(
            CODEX_THREAD_INDEX_TABLE,
            sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.alter_column(CODEX_THREAD_INDEX_TABLE, "lease_generation", server_default=None)
        op.create_index(
            "ix_codex_thread_index_runtime_watchdog",
            CODEX_THREAD_INDEX_TABLE,
            ["phase", "lease_expires_at", "last_activity_at"],
        )

    @staticmethod
    def downgrade() -> None:
        """删除仅用于运行态恢复的索引和字段。"""

        op.drop_index(
            "ix_codex_thread_index_runtime_watchdog",
            table_name=CODEX_THREAD_INDEX_TABLE,
        )
        op.drop_column(CODEX_THREAD_INDEX_TABLE, "lease_expires_at")
        op.drop_column(CODEX_THREAD_INDEX_TABLE, "lease_generation")
        op.drop_column(CODEX_THREAD_INDEX_TABLE, "stalled_reason")
        op.drop_column(CODEX_THREAD_INDEX_TABLE, "last_activity_at")
        op.drop_column(CODEX_THREAD_INDEX_TABLE, "phase")
        op.drop_column(CODEX_THREAD_INDEX_TABLE, "runtime_turn_id")


upgrade = CodexTurnRuntimeMigration.upgrade
downgrade = CodexTurnRuntimeMigration.downgrade
