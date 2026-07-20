"""
202607051000创建密钥环快照表迁移模块。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

REVISION_ID = "202607051000"
DOWN_REVISION_ID = "202607021200"
KEY_RING_SNAPSHOT_TABLE_NAME = "key_ring_snapshot"
KEY_RING_SNAPSHOT_FAMILY_UNIQUE_NAME = "uq_key_ring_snapshot_key_family"
KEY_RING_SNAPSHOT_FAMILY_INDEX_NAME = "ix_key_ring_snapshot_key_family"
KEY_RING_SNAPSHOT_VERSION_INDEX_NAME = "ix_key_ring_snapshot_version_digest"
MAX_KEY_FAMILY_LENGTH = 128
VERSION_DIGEST_LENGTH = 64
CURRENT_TIMESTAMP_SQL = sa.text("CURRENT_TIMESTAMP")

revision = REVISION_ID
down_revision = DOWN_REVISION_ID
branch_labels = None
depends_on = None


class Migration:
    """
    密钥环快照表迁移封装类型。
    """

    def upgrade(self) -> None:
        """
        执行升级。
        """

        op.create_table(
            KEY_RING_SNAPSHOT_TABLE_NAME,
            sa.Column(
                "key_ring_snapshot_id",
                postgresql.UUID(as_uuid=True),
                nullable=False,
            ),
            sa.Column(
                "key_family",
                sa.String(length=MAX_KEY_FAMILY_LENGTH),
                nullable=False,
            ),
            sa.Column("encrypted_snapshot_json", sa.Text(), nullable=False),
            sa.Column(
                "version_digest",
                sa.String(length=VERSION_DIGEST_LENGTH),
                nullable=False,
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=CURRENT_TIMESTAMP_SQL,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=CURRENT_TIMESTAMP_SQL,
            ),
            sa.PrimaryKeyConstraint(
                "key_ring_snapshot_id",
                name="pk_key_ring_snapshot",
            ),
            sa.UniqueConstraint(
                "key_family",
                name=KEY_RING_SNAPSHOT_FAMILY_UNIQUE_NAME,
            ),
        )
        op.create_index(
            KEY_RING_SNAPSHOT_FAMILY_INDEX_NAME,
            KEY_RING_SNAPSHOT_TABLE_NAME,
            ["key_family"],
            unique=False,
        )
        op.create_index(
            KEY_RING_SNAPSHOT_VERSION_INDEX_NAME,
            KEY_RING_SNAPSHOT_TABLE_NAME,
            ["version_digest"],
            unique=False,
        )

    def downgrade(self) -> None:
        """
        执行降级。
        """

        op.drop_index(
            KEY_RING_SNAPSHOT_VERSION_INDEX_NAME,
            table_name=KEY_RING_SNAPSHOT_TABLE_NAME,
        )
        op.drop_index(
            KEY_RING_SNAPSHOT_FAMILY_INDEX_NAME,
            table_name=KEY_RING_SNAPSHOT_TABLE_NAME,
        )
        op.drop_table(KEY_RING_SNAPSHOT_TABLE_NAME)


upgrade = Migration().upgrade
downgrade = Migration().downgrade
