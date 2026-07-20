"""
202605251640 加固刷新令牌约束迁移。
"""

from __future__ import annotations

from alembic import op

REVISION_ID = "202605251640"
DOWN_REVISION_ID = "202605231821"
AUTH_REFRESH_TOKEN_TABLE_NAME = "auth_refresh_token"
AUTH_USER_TABLE_NAME = "auth_user"
AUTH_REFRESH_TOKEN_SUBJECT_FK_NAME = "fk_auth_refresh_token_subject_id_auth_user"
AUTH_REFRESH_TOKEN_ROTATED_TO_FK_NAME = (
    "fk_auth_refresh_token_rotated_to_token_id_auth_refresh_token"
)

revision = REVISION_ID
down_revision = DOWN_REVISION_ID
branch_labels = None
depends_on = None


class Migration:
    """
    刷新令牌约束加固迁移。
    """

    def upgrade(self) -> None:
        """
        执行升级。

        :returns: 无返回值。
        :rtype: None
        """

        op.create_foreign_key(
            AUTH_REFRESH_TOKEN_SUBJECT_FK_NAME,
            AUTH_REFRESH_TOKEN_TABLE_NAME,
            AUTH_USER_TABLE_NAME,
            ["subject_id"],
            ["subject_id"],
            ondelete="CASCADE",
        )
        op.create_foreign_key(
            AUTH_REFRESH_TOKEN_ROTATED_TO_FK_NAME,
            AUTH_REFRESH_TOKEN_TABLE_NAME,
            AUTH_REFRESH_TOKEN_TABLE_NAME,
            ["rotated_to_token_id"],
            ["refresh_token_id"],
            ondelete="RESTRICT",
        )

    def downgrade(self) -> None:
        """
        执行降级。

        :returns: 无返回值。
        :rtype: None
        """

        op.drop_constraint(
            AUTH_REFRESH_TOKEN_ROTATED_TO_FK_NAME,
            AUTH_REFRESH_TOKEN_TABLE_NAME,
            type_="foreignkey",
        )
        op.drop_constraint(
            AUTH_REFRESH_TOKEN_SUBJECT_FK_NAME,
            AUTH_REFRESH_TOKEN_TABLE_NAME,
            type_="foreignkey",
        )


upgrade = Migration().upgrade
downgrade = Migration().downgrade
