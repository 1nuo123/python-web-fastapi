"""为 Codex 工作区增加不含正文的执行偏好。"""

from __future__ import annotations

from typing import Final

import sqlalchemy as sa
from alembic import op

REVISION_ID: Final = "202608190230"
DOWN_REVISION_ID: Final = "202608190130"
CODEX_WORKSPACE_TABLE: Final = "codex_workspace"

revision = REVISION_ID
down_revision = DOWN_REVISION_ID
branch_labels = None
depends_on = None


class CodexWorkspaceExecutionPreferencesMigration:
    """保存可重验证的模型和安全策略偏好，不保存正文或授权凭据。"""

    @staticmethod
    def upgrade() -> None:
        """为历史工作区提供空 JSON 默认值，读取时由强类型契约归一化。"""

        op.add_column(
            CODEX_WORKSPACE_TABLE,
            sa.Column(
                "execution_preferences",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            ),
        )
        op.alter_column(
            CODEX_WORKSPACE_TABLE,
            "execution_preferences",
            server_default=None,
        )

    @staticmethod
    def downgrade() -> None:
        """移除只用于工作区级执行偏好的 JSON 列。"""

        op.drop_column(CODEX_WORKSPACE_TABLE, "execution_preferences")


upgrade = CodexWorkspaceExecutionPreferencesMigration.upgrade
downgrade = CodexWorkspaceExecutionPreferencesMigration.downgrade
