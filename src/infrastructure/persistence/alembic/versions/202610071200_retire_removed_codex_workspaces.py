"""为 Agent 删除的项目身份保留不可复活的终态。"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "202610071200"
down_revision = "202609291900"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """旧 disabled 状态无法区分手动停用，不据此猜测历史删除。"""
    op.add_column(
        "codex_workspace", sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    """回退删除标记列，保留原停用状态。"""
    op.drop_column("codex_workspace", "retired_at")
