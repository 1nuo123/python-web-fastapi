"""统一 Codex 会话标题、活动时间与置顶索引。"""

from __future__ import annotations

from typing import Final

import sqlalchemy as sa
from alembic import op

REVISION_ID: Final = "202608151820"
DOWN_REVISION_ID: Final = "202608101300"

revision = REVISION_ID
down_revision = DOWN_REVISION_ID
branch_labels = None
depends_on = None


class CodexConversationIndexMigration:
    """执行可回滚且幂等数据表达的会话索引迁移。"""

    @staticmethod
    def upgrade() -> None:
        """补齐字段、历史数据和稳定排序索引。"""

        op.add_column(
            "codex_thread_index",
            sa.Column("title_source", sa.String(length=32), nullable=True),
        )
        op.add_column(
            "codex_thread_index",
            sa.Column("model_provider", sa.String(length=128), nullable=True),
        )
        op.add_column(
            "codex_thread_index",
            sa.Column("recency_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.add_column(
            "codex_thread_index",
            sa.Column(
                "is_pinned",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )
        op.add_column(
            "codex_workspace",
            sa.Column(
                "is_pinned",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )
        op.execute(
            sa.text(
                """
                UPDATE codex_thread_index
                SET
                    title_source = CASE
                        WHEN NULLIF(BTRIM(display_name), '') IS NULL
                        THEN 'new_conversation'
                        ELSE 'app_server'
                    END,
                    display_name = COALESCE(
                        NULLIF(BTRIM(display_name), ''),
                        '新会话 · ' || TO_CHAR(
                            COALESCE(created_at, updated_at, last_synced_at),
                            'YYYY-MM-DD HH24:MI'
                        )
                    ),
                    created_at = COALESCE(created_at, updated_at, last_synced_at),
                    recency_at = COALESCE(updated_at, created_at, last_synced_at)
                """
            )
        )
        op.alter_column("codex_thread_index", "display_name", nullable=False)
        op.alter_column("codex_thread_index", "title_source", nullable=False)
        op.alter_column("codex_thread_index", "created_at", nullable=False)
        op.alter_column("codex_thread_index", "recency_at", nullable=False)
        op.alter_column("codex_thread_index", "is_pinned", server_default=None)
        op.alter_column("codex_workspace", "is_pinned", server_default=None)
        op.drop_index(
            "ix_codex_thread_index_workspace_archived_updated",
            table_name="codex_thread_index",
        )
        op.create_index(
            "ix_codex_thread_index_workspace_conversation_order",
            "codex_thread_index",
            [
                "workspace_id",
                "archived",
                "is_pinned",
                "recency_at",
                "created_at",
                "upstream_thread_id",
            ],
        )
        op.create_index(
            "ix_codex_thread_index_owner_conversation_order",
            "codex_thread_index",
            [
                "owner_subject_id",
                "archived",
                "is_pinned",
                "recency_at",
                "created_at",
                "upstream_thread_id",
            ],
        )
        op.create_index(
            "ix_codex_workspace_owner_pin_order",
            "codex_workspace",
            ["owner_subject_id", "is_pinned", "updated_at", "workspace_id"],
        )

    @staticmethod
    def downgrade() -> None:
        """恢复旧字段可空约束与旧排序索引。"""

        op.drop_index(
            "ix_codex_workspace_owner_pin_order",
            table_name="codex_workspace",
        )
        op.drop_index(
            "ix_codex_thread_index_owner_conversation_order",
            table_name="codex_thread_index",
        )
        op.drop_index(
            "ix_codex_thread_index_workspace_conversation_order",
            table_name="codex_thread_index",
        )
        op.create_index(
            "ix_codex_thread_index_workspace_archived_updated",
            "codex_thread_index",
            ["workspace_id", "archived", "updated_at"],
        )
        op.alter_column("codex_thread_index", "display_name", nullable=True)
        op.alter_column("codex_thread_index", "created_at", nullable=True)
        op.drop_column("codex_workspace", "is_pinned")
        op.drop_column("codex_thread_index", "is_pinned")
        op.drop_column("codex_thread_index", "recency_at")
        op.drop_column("codex_thread_index", "model_provider")
        op.drop_column("codex_thread_index", "title_source")


upgrade = CodexConversationIndexMigration.upgrade
downgrade = CodexConversationIndexMigration.downgrade
