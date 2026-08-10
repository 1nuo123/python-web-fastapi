"""增加 Codex 设备公钥和授权审计结构。"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

REVISION_ID = "202608071200"
DOWN_REVISION_ID = "202607311200"
CODEX_HOST_CAPABILITY_MIGRATION_STATEMENT = """
UPDATE codex_host
SET capabilities = jsonb_build_object('items', '[]'::jsonb)
WHERE jsonb_typeof(capabilities) <> 'object'
   OR NOT (capabilities ? 'items')
"""

revision = REVISION_ID
down_revision = DOWN_REVISION_ID
branch_labels = None
depends_on = None


class Migration:
    """Codex 设备身份迁移。"""

    def upgrade(self) -> None:
        """创建设备公钥和授权审计表。"""

        op.execute(sa.text(CODEX_HOST_CAPABILITY_MIGRATION_STATEMENT))

        op.create_table(
            "codex_host_device_key",
            sa.Column("key_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("enrollment_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("host_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("owner_subject_id", sa.String(128), nullable=False),
            sa.Column("public_key", sa.LargeBinary(32), nullable=False),
            sa.Column("fingerprint", sa.String(64), nullable=False),
            sa.Column("state", sa.String(32), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("retire_after", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.ForeignKeyConstraint(
                ["host_id"],
                ["codex_host.host_id"],
                name="fk_codex_host_device_key_host",
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["owner_subject_id"],
                ["auth_user.subject_id"],
                name="fk_codex_host_device_key_owner",
                ondelete="RESTRICT",
            ),
            sa.PrimaryKeyConstraint("key_id", name="pk_codex_host_device_key"),
            sa.UniqueConstraint(
                "enrollment_id",
                name="uq_codex_host_device_key_enrollment",
            ),
            sa.UniqueConstraint(
                "host_id",
                "fingerprint",
                name="uq_codex_host_device_key_host_fingerprint",
            ),
        )
        op.create_index(
            "ix_codex_host_device_key_host_state",
            "codex_host_device_key",
            ["host_id", "state"],
        )
        op.create_table(
            "codex_device_authorization_audit",
            sa.Column("audit_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("enrollment_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("host_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("owner_subject_id", sa.String(128), nullable=False),
            sa.Column("decision", sa.String(32), nullable=False),
            sa.Column("idempotency_key", sa.String(128), nullable=False),
            sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["host_id"],
                ["codex_host.host_id"],
                name="fk_codex_device_authorization_audit_host",
                ondelete="SET NULL",
            ),
            sa.ForeignKeyConstraint(
                ["owner_subject_id"],
                ["auth_user.subject_id"],
                name="fk_codex_device_authorization_audit_owner",
                ondelete="RESTRICT",
            ),
            sa.PrimaryKeyConstraint(
                "audit_id",
                name="pk_codex_device_authorization_audit",
            ),
            sa.UniqueConstraint(
                "enrollment_id",
                "idempotency_key",
                name="uq_codex_device_authorization_audit_idempotency",
            ),
        )
        op.create_index(
            "ix_codex_device_authorization_audit_owner_occurred",
            "codex_device_authorization_audit",
            ["owner_subject_id", "occurred_at"],
        )

    def downgrade(self) -> None:
        """按依赖逆序删除设备身份结构。"""

        op.drop_table("codex_device_authorization_audit")
        op.drop_table("codex_host_device_key")


upgrade = Migration().upgrade
downgrade = Migration().downgrade
