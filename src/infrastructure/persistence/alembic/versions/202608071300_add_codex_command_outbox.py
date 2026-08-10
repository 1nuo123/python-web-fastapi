"""增加加密 Codex command outbox。"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

REVISION_ID = "202608071300"
DOWN_REVISION_ID = "202608071200"
revision = REVISION_ID
down_revision = DOWN_REVISION_ID
branch_labels = None
depends_on = None


class Migration:
    """Codex command outbox 迁移。"""

    def upgrade(self) -> None:
        op.create_table(
            "codex_command_outbox",
            sa.Column("outbox_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("operation_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("command_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("host_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("owner_subject_id", sa.String(128), nullable=False),
            sa.Column("cipher_algorithm", sa.String(64), nullable=False),
            sa.Column("cipher_key_id", sa.String(128), nullable=False),
            sa.Column("cipher_nonce", sa.LargeBinary(12), nullable=False),
            sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
            sa.Column("aad_digest", sa.String(64), nullable=False),
            sa.Column("state", sa.String(32), nullable=False),
            sa.Column("route_epoch", sa.Integer(), nullable=True),
            sa.Column("dispatch_attempt", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("claimed_by", sa.String(128), nullable=True),
            sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_error_code", sa.String(128), nullable=True),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["operation_id"],
                ["codex_control_operation.operation_id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(["host_id"], ["codex_host.host_id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("outbox_id"),
            sa.UniqueConstraint("operation_id", name="uq_codex_command_outbox_operation"),
            sa.UniqueConstraint("command_id", name="uq_codex_command_outbox_command"),
        )
        op.create_index(
            "ix_codex_command_outbox_ready",
            "codex_command_outbox",
            ["state", "available_at"],
        )
        op.create_index(
            "ix_codex_command_outbox_host_state",
            "codex_command_outbox",
            ["host_id", "state"],
        )

    def downgrade(self) -> None:
        op.drop_table("codex_command_outbox")


upgrade = Migration().upgrade
downgrade = Migration().downgrade
