"""增加用户直接授权 scope 关联。"""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

REVISION_ID = "202608101100"
DOWN_REVISION_ID = "202608101000"
AUTH_USER_SCOPE_TABLE_NAME = "auth_user_scope"
CURRENT_TIMESTAMP_SQL = sa.text("CURRENT_TIMESTAMP")

revision = REVISION_ID
down_revision = DOWN_REVISION_ID
branch_labels = None
depends_on = None


class Migration:
    """建立用户直接授权的数据库权威关系。"""

    def upgrade(self) -> None:
        """创建用户直接 scope 关联表。"""

        op.create_table(
            AUTH_USER_SCOPE_TABLE_NAME,
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("scope_code", sa.String(length=128), nullable=False),
            self._build_created_at_column(),
            self._build_updated_at_column(),
            sa.ForeignKeyConstraint(
                ["user_id"],
                ["auth_user.user_id"],
                name="fk_auth_user_scope_user_id_auth_user",
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["scope_code"],
                ["auth_scope.scope_code"],
                name="fk_auth_user_scope_scope_code_auth_scope",
                ondelete="RESTRICT",
            ),
            sa.PrimaryKeyConstraint(
                "user_id",
                "scope_code",
                name="pk_auth_user_scope",
            ),
        )

    def downgrade(self) -> None:
        """删除用户直接 scope 关联表。"""

        op.drop_table(AUTH_USER_SCOPE_TABLE_NAME)

    def _build_created_at_column(self) -> sa.Column[datetime]:
        """构建创建时间列。"""

        return sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=CURRENT_TIMESTAMP_SQL,
        )

    def _build_updated_at_column(self) -> sa.Column[datetime]:
        """构建更新时间列。"""

        return sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=CURRENT_TIMESTAMP_SQL,
        )


upgrade = Migration().upgrade
downgrade = Migration().downgrade
