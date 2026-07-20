"""
202605151600创建鉴权表集合基础设施模块。
"""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

REVISION_ID = "202605151600"
AUTH_USER_TABLE_NAME = "auth_user"
AUTH_ROLE_TABLE_NAME = "auth_role"
AUTH_USER_ROLE_TABLE_NAME = "auth_user_role"
AUTH_ROLE_SCOPE_TABLE_NAME = "auth_role_scope"
AUTH_REFRESH_TOKEN_TABLE_NAME = "auth_refresh_token"
AUTH_USER_SUBJECT_UNIQUE_NAME = "uq_auth_user_subject_id"
AUTH_USER_USERNAME_UNIQUE_NAME = "uq_auth_user_username"
AUTH_ROLE_KEY_UNIQUE_NAME = "uq_auth_role_role_key"
AUTH_REFRESH_TOKEN_SESSION_INDEX_NAME = "ix_auth_refresh_token_token_session_id"
AUTH_REFRESH_TOKEN_USER_INDEX_NAME = "ix_auth_refresh_token_user_id"
AUTH_REFRESH_TOKEN_SUBJECT_INDEX_NAME = "ix_auth_refresh_token_subject_id"
AUTH_REFRESH_TOKEN_EXPIRES_INDEX_NAME = "ix_auth_refresh_token_expires_at"
AUTH_REFRESH_TOKEN_ROTATED_TO_INDEX_NAME = "ix_auth_refresh_token_rotated_to_token_id"
CURRENT_TIMESTAMP_SQL = sa.text("CURRENT_TIMESTAMP")

revision = REVISION_ID
down_revision = None
branch_labels = None
depends_on = None


class Migration:
    """
    迁移类型，用于封装当前模块中的相关行为或状态。
    """

    def upgrade(self) -> None:
        """
        处理升级。

        :returns: 无返回值。
        :rtype: None
        """

        self._create_auth_user_table()
        self._create_auth_role_table()
        self._create_auth_user_role_table()
        self._create_auth_role_scope_table()
        self._create_auth_refresh_token_table()

    def downgrade(self) -> None:
        """
        处理降级。

        :returns: 无返回值。
        :rtype: None
        """

        op.drop_index(
            AUTH_REFRESH_TOKEN_ROTATED_TO_INDEX_NAME,
            table_name=AUTH_REFRESH_TOKEN_TABLE_NAME,
        )
        op.drop_index(
            AUTH_REFRESH_TOKEN_EXPIRES_INDEX_NAME,
            table_name=AUTH_REFRESH_TOKEN_TABLE_NAME,
        )
        op.drop_index(
            AUTH_REFRESH_TOKEN_SUBJECT_INDEX_NAME,
            table_name=AUTH_REFRESH_TOKEN_TABLE_NAME,
        )
        op.drop_index(
            AUTH_REFRESH_TOKEN_USER_INDEX_NAME,
            table_name=AUTH_REFRESH_TOKEN_TABLE_NAME,
        )
        op.drop_index(
            AUTH_REFRESH_TOKEN_SESSION_INDEX_NAME,
            table_name=AUTH_REFRESH_TOKEN_TABLE_NAME,
        )
        op.drop_table(AUTH_REFRESH_TOKEN_TABLE_NAME)
        op.drop_table(AUTH_ROLE_SCOPE_TABLE_NAME)
        op.drop_table(AUTH_USER_ROLE_TABLE_NAME)
        op.drop_table(AUTH_ROLE_TABLE_NAME)
        op.drop_table(AUTH_USER_TABLE_NAME)

    def _build_created_at_column(self) -> sa.Column[datetime]:
        """
        构建已创建在列。

        :returns: 返回当前操作结果。
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
        构建已更新在列。

        :returns: 返回当前操作结果。
        :rtype: sa.Column
        """

        return sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=CURRENT_TIMESTAMP_SQL,
        )

    def _create_auth_user_table(self) -> None:
        """
        创建鉴权用户表。

        :returns: 无返回值。
        :rtype: None
        """

        op.create_table(
            AUTH_USER_TABLE_NAME,
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("subject_id", sa.String(length=128), nullable=False),
            sa.Column("username", sa.String(length=128), nullable=False),
            sa.Column("password_hash", sa.Text(), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            self._build_created_at_column(),
            self._build_updated_at_column(),
            sa.PrimaryKeyConstraint("user_id", name="pk_auth_user"),
            sa.UniqueConstraint("subject_id", name=AUTH_USER_SUBJECT_UNIQUE_NAME),
            sa.UniqueConstraint("username", name=AUTH_USER_USERNAME_UNIQUE_NAME),
        )

    def _create_auth_role_table(self) -> None:
        """
        创建鉴权角色表。

        :returns: 无返回值。
        :rtype: None
        """

        op.create_table(
            AUTH_ROLE_TABLE_NAME,
            sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("role_key", sa.String(length=64), nullable=False),
            sa.Column("role_name", sa.String(length=128), nullable=False),
            self._build_created_at_column(),
            self._build_updated_at_column(),
            sa.PrimaryKeyConstraint("role_id", name="pk_auth_role"),
            sa.UniqueConstraint("role_key", name=AUTH_ROLE_KEY_UNIQUE_NAME),
        )

    def _create_auth_user_role_table(self) -> None:
        """
        创建鉴权用户角色表。

        :returns: 无返回值。
        :rtype: None
        """

        op.create_table(
            AUTH_USER_ROLE_TABLE_NAME,
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=False),
            self._build_created_at_column(),
            self._build_updated_at_column(),
            sa.ForeignKeyConstraint(
                ["user_id"],
                [f"{AUTH_USER_TABLE_NAME}.user_id"],
                name="fk_auth_user_role_user_id_auth_user",
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["role_id"],
                [f"{AUTH_ROLE_TABLE_NAME}.role_id"],
                name="fk_auth_user_role_role_id_auth_role",
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("user_id", "role_id", name="pk_auth_user_role"),
        )

    def _create_auth_role_scope_table(self) -> None:
        """
        创建鉴权角色作用域表。

        :returns: 无返回值。
        :rtype: None
        """

        op.create_table(
            AUTH_ROLE_SCOPE_TABLE_NAME,
            sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("scope_code", sa.String(length=128), nullable=False),
            self._build_created_at_column(),
            self._build_updated_at_column(),
            sa.ForeignKeyConstraint(
                ["role_id"],
                [f"{AUTH_ROLE_TABLE_NAME}.role_id"],
                name="fk_auth_role_scope_role_id_auth_role",
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("role_id", "scope_code", name="pk_auth_role_scope"),
        )

    def _create_auth_refresh_token_table(self) -> None:
        """
        创建鉴权刷新令牌表。

        :returns: 无返回值。
        :rtype: None
        """

        op.create_table(
            AUTH_REFRESH_TOKEN_TABLE_NAME,
            sa.Column(
                "refresh_token_id",
                postgresql.UUID(as_uuid=True),
                nullable=False,
            ),
            sa.Column(
                "token_session_id",
                postgresql.UUID(as_uuid=True),
                nullable=False,
            ),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("subject_id", sa.String(length=128), nullable=False),
            sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "rotated_to_token_id",
                postgresql.UUID(as_uuid=True),
                nullable=True,
            ),
            self._build_created_at_column(),
            self._build_updated_at_column(),
            sa.ForeignKeyConstraint(
                ["user_id"],
                [f"{AUTH_USER_TABLE_NAME}.user_id"],
                name="fk_auth_refresh_token_user_id_auth_user",
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint(
                "refresh_token_id",
                name="pk_auth_refresh_token",
            ),
        )
        op.create_index(
            AUTH_REFRESH_TOKEN_SESSION_INDEX_NAME,
            AUTH_REFRESH_TOKEN_TABLE_NAME,
            ["token_session_id"],
            unique=False,
        )
        op.create_index(
            AUTH_REFRESH_TOKEN_USER_INDEX_NAME,
            AUTH_REFRESH_TOKEN_TABLE_NAME,
            ["user_id"],
            unique=False,
        )
        op.create_index(
            AUTH_REFRESH_TOKEN_SUBJECT_INDEX_NAME,
            AUTH_REFRESH_TOKEN_TABLE_NAME,
            ["subject_id"],
            unique=False,
        )
        op.create_index(
            AUTH_REFRESH_TOKEN_EXPIRES_INDEX_NAME,
            AUTH_REFRESH_TOKEN_TABLE_NAME,
            ["expires_at"],
            unique=False,
        )
        op.create_index(
            AUTH_REFRESH_TOKEN_ROTATED_TO_INDEX_NAME,
            AUTH_REFRESH_TOKEN_TABLE_NAME,
            ["rotated_to_token_id"],
            unique=False,
        )


upgrade = Migration().upgrade
downgrade = Migration().downgrade
