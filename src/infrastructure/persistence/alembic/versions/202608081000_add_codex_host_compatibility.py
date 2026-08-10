"""持久化 Codex 主机兼容状态。"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

REVISION_ID = "202608081000"
DOWN_REVISION_ID = "202608071400"
CODEX_HOST_TABLE_NAME = "codex_host"
COMPATIBILITY_UNKNOWN_STATE = "unknown"

revision = REVISION_ID
down_revision = DOWN_REVISION_ID
branch_labels = None
depends_on = None


class Migration:
    """保存握手判定，供后续 HTTP mutation 复用。"""

    def upgrade(self) -> None:
        """增加兼容状态和原因字段。"""

        op.add_column(
            CODEX_HOST_TABLE_NAME,
            sa.Column(
                "compatibility_state",
                sa.String(32),
                nullable=False,
                server_default=COMPATIBILITY_UNKNOWN_STATE,
            ),
        )
        op.add_column(
            CODEX_HOST_TABLE_NAME,
            sa.Column("compatibility_reason_code", sa.String(128), nullable=True),
        )

    def downgrade(self) -> None:
        """按逆序删除兼容字段。"""

        op.drop_column(CODEX_HOST_TABLE_NAME, "compatibility_reason_code")
        op.drop_column(CODEX_HOST_TABLE_NAME, "compatibility_state")


upgrade = Migration().upgrade
downgrade = Migration().downgrade
