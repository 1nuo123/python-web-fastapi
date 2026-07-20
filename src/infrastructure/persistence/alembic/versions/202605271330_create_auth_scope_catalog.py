"""
202605271330 创建鉴权 scope 目录表。
"""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from alembic import op

REVISION_ID = "202605271330"
DOWN_REVISION_ID = "202605260859"
AUTH_SCOPE_TABLE_NAME = "auth_scope"
AUTH_SCOPE_ENABLED_INDEX_NAME = "ix_auth_scope_enabled"
AUTH_SCOPE_KIND_INDEX_NAME = "ix_auth_scope_scope_kind"
CURRENT_TIMESTAMP_SQL = sa.text("CURRENT_TIMESTAMP")
SCOPE_CODE_MAX_LENGTH = 128
SCOPE_NAME_MAX_LENGTH = 128
SCOPE_KIND_MAX_LENGTH = 32

revision = REVISION_ID
down_revision = DOWN_REVISION_ID
branch_labels = None
depends_on = None


class Migration:
    """
    鉴权 scope 目录迁移。
    """

    def upgrade(self) -> None:
        """
        执行升级。

        :returns: 无返回值。
        :rtype: None
        """

        op.create_table(
            AUTH_SCOPE_TABLE_NAME,
            sa.Column(
                "scope_code",
                sa.String(length=SCOPE_CODE_MAX_LENGTH),
                nullable=False,
            ),
            sa.Column(
                "scope_name",
                sa.String(length=SCOPE_NAME_MAX_LENGTH),
                nullable=False,
            ),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column(
                "scope_kind",
                sa.String(length=SCOPE_KIND_MAX_LENGTH),
                nullable=False,
            ),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            self._build_created_at_column(),
            self._build_updated_at_column(),
            sa.PrimaryKeyConstraint("scope_code", name="pk_auth_scope"),
        )
        op.create_index(
            AUTH_SCOPE_ENABLED_INDEX_NAME,
            AUTH_SCOPE_TABLE_NAME,
            ["enabled"],
            unique=False,
        )
        op.create_index(
            AUTH_SCOPE_KIND_INDEX_NAME,
            AUTH_SCOPE_TABLE_NAME,
            ["scope_kind"],
            unique=False,
        )

    def downgrade(self) -> None:
        """
        执行降级。

        :returns: 无返回值。
        :rtype: None
        """

        op.drop_index(AUTH_SCOPE_KIND_INDEX_NAME, table_name=AUTH_SCOPE_TABLE_NAME)
        op.drop_index(AUTH_SCOPE_ENABLED_INDEX_NAME, table_name=AUTH_SCOPE_TABLE_NAME)
        op.drop_table(AUTH_SCOPE_TABLE_NAME)

    def _build_created_at_column(self) -> sa.Column[datetime]:
        """
        构建创建时间列。

        :returns: 创建时间列。
        :rtype: sa.Column
        """

        return sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=CURRENT_TIMESTAMP_SQL,
        )

    def _build_updated_at_column(self) -> sa.Column[datetime]:
        """
        构建更新时间列。

        :returns: 更新时间列。
        :rtype: sa.Column
        """

        return sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=CURRENT_TIMESTAMP_SQL,
        )


upgrade = Migration().upgrade
downgrade = Migration().downgrade
