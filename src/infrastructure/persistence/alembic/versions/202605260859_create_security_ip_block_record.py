"""
202605260859 创建安全 IP 封禁记录表。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

REVISION_ID = "202605260859"
DOWN_REVISION_ID = "202605251640"
SECURITY_IP_BLOCK_RECORD_TABLE_NAME = "security_ip_block_record"
IP_DIGEST_INDEX_NAME = "ix_security_ip_block_record_ip_digest"
STATUS_INDEX_NAME = "ix_security_ip_block_record_status"
BLOCKED_UNTIL_INDEX_NAME = "ix_security_ip_block_record_blocked_until_epoch"

revision = REVISION_ID
down_revision = DOWN_REVISION_ID
branch_labels = None
depends_on = None


class Migration:
    """
    安全 IP 封禁记录迁移。
    """

    def upgrade(self) -> None:
        """
        执行升级。
        """

        op.create_table(
            SECURITY_IP_BLOCK_RECORD_TABLE_NAME,
            sa.Column(
                "record_id",
                postgresql.UUID(as_uuid=True),
                nullable=False,
            ),
            sa.Column("ip_digest", sa.String(length=128), nullable=False),
            sa.Column("reason", sa.String(length=64), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("blocked_until_epoch", sa.Integer(), nullable=False),
            sa.Column("released_reason", sa.String(length=256), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("record_id"),
        )
        op.create_index(
            IP_DIGEST_INDEX_NAME,
            SECURITY_IP_BLOCK_RECORD_TABLE_NAME,
            ["ip_digest"],
        )
        op.create_index(
            STATUS_INDEX_NAME,
            SECURITY_IP_BLOCK_RECORD_TABLE_NAME,
            ["status"],
        )
        op.create_index(
            BLOCKED_UNTIL_INDEX_NAME,
            SECURITY_IP_BLOCK_RECORD_TABLE_NAME,
            ["blocked_until_epoch"],
        )

    def downgrade(self) -> None:
        """
        执行降级。
        """

        op.drop_index(BLOCKED_UNTIL_INDEX_NAME, table_name=SECURITY_IP_BLOCK_RECORD_TABLE_NAME)
        op.drop_index(STATUS_INDEX_NAME, table_name=SECURITY_IP_BLOCK_RECORD_TABLE_NAME)
        op.drop_index(IP_DIGEST_INDEX_NAME, table_name=SECURITY_IP_BLOCK_RECORD_TABLE_NAME)
        op.drop_table(SECURITY_IP_BLOCK_RECORD_TABLE_NAME)


upgrade = Migration().upgrade
downgrade = Migration().downgrade
