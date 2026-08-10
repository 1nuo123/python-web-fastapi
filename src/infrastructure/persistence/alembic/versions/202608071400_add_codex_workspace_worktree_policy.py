"""增加 Codex 工作区隔离策略字段。"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

REVISION_ID = "202608071400"
DOWN_REVISION_ID = "202608071300"
revision = REVISION_ID
down_revision = DOWN_REVISION_ID
branch_labels = None
depends_on = None


class Migration:
    """持久化可选 worktree 策略，默认关闭隔离。"""

    def upgrade(self) -> None:
        op.add_column(
            "codex_workspace",
            sa.Column(
                "worktree_policy",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            ),
        )

    def downgrade(self) -> None:
        op.drop_column("codex_workspace", "worktree_policy")


upgrade = Migration().upgrade
downgrade = Migration().downgrade
