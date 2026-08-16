"""创建 Codex 控制面 Phase 1 数据结构与作用域。"""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

REVISION_ID = "202607311200"
DOWN_REVISION_ID = "202607051000"
CURRENT_TIMESTAMP_SQL = sa.text("CURRENT_TIMESTAMP")

revision = REVISION_ID
down_revision = DOWN_REVISION_ID
branch_labels = None
depends_on = None

CODEX_SCOPE_ROWS = (
    ("codex:read", "Codex读取"),
    ("codex:operate", "Codex操作"),
    ("codex:approve", "Codex审批"),
    ("codex:host_manage", "Codex主机管理"),
    ("codex:files", "Codex文件访问"),
    ("codex:terminal", "Codex终端访问"),
    ("codex:network", "Codex联网访问"),
    ("codex:full_access", "Codex完全访问"),
    ("codex:admin_manage", "Codex租户管理"),
    ("codex:admin_content_access", "Codex跨租户内容访问"),
)


class Migration:
    """Codex 控制面 Phase 1 迁移。"""

    def upgrade(self) -> None:
        """创建表、索引、约束并登记稳定 scope。"""

        self._create_host_table()
        self._create_agent_credential_table()
        self._create_workspace_table()
        self._create_thread_index_table()
        self._create_control_operation_table()
        self._create_approval_audit_table()
        self._insert_scope_rows()

    def downgrade(self) -> None:
        """按依赖逆序删除 Phase 1 数据结构和 scope。"""

        scope_codes = [scope_code for scope_code, _scope_name in CODEX_SCOPE_ROWS]
        op.execute(
            sa.text("DELETE FROM auth_role_scope WHERE scope_code = ANY(:scope_codes)").bindparams(
                scope_codes=scope_codes
            )
        )
        op.execute(
            sa.text("DELETE FROM auth_scope WHERE scope_code = ANY(:scope_codes)").bindparams(
                scope_codes=scope_codes
            )
        )
        op.drop_table("codex_approval_audit")
        op.drop_table("codex_control_operation")
        op.drop_table("codex_thread_index")
        op.drop_table("codex_workspace")
        op.drop_table("codex_agent_credential")
        op.drop_table("codex_host")

    def _create_host_table(self) -> None:
        op.create_table(
            "codex_host",
            sa.Column("host_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("owner_subject_id", sa.String(128), nullable=False),
            sa.Column("display_name", sa.String(128), nullable=False),
            sa.Column("platform", sa.String(64), nullable=False),
            sa.Column("agent_version", sa.String(64), nullable=True),
            sa.Column("codex_version", sa.String(64), nullable=True),
            sa.Column("agent_protocol_version", sa.String(64), nullable=True),
            sa.Column("app_server_schema_digest", sa.String(128), nullable=True),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("capabilities", postgresql.JSONB(), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            self._created_at_column(),
            self._updated_at_column(),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.ForeignKeyConstraint(
                ["owner_subject_id"],
                ["auth_user.subject_id"],
                name="fk_codex_host_owner_subject_id_auth_user",
                ondelete="RESTRICT",
            ),
            sa.PrimaryKeyConstraint("host_id", name="pk_codex_host"),
        )
        op.create_index(
            "ix_codex_host_owner_revoked", "codex_host", ["owner_subject_id", "revoked_at"]
        )
        op.create_index("ix_codex_host_status_last_seen", "codex_host", ["status", "last_seen_at"])

    def _create_agent_credential_table(self) -> None:
        op.create_table(
            "codex_agent_credential",
            sa.Column("credential_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("host_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("token_digest", sa.String(128), nullable=False),
            sa.Column("key_id", sa.String(128), nullable=False),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(
                ["host_id"],
                ["codex_host.host_id"],
                name="fk_codex_agent_credential_host_id_codex_host",
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("credential_id", name="pk_codex_agent_credential"),
            sa.UniqueConstraint(
                "token_digest",
                name="uq_codex_agent_credential_token_digest",
            ),
        )
        op.create_index(
            "ix_codex_agent_credential_host_status",
            "codex_agent_credential",
            ["host_id", "status"],
        )

    def _create_workspace_table(self) -> None:
        op.create_table(
            "codex_workspace",
            sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("host_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("owner_subject_id", sa.String(128), nullable=False),
            sa.Column("agent_workspace_key", sa.String(128), nullable=False),
            sa.Column("display_name", sa.String(128), nullable=False),
            sa.Column("repo_fingerprint", sa.String(128), nullable=True),
            sa.Column("default_branch", sa.String(256), nullable=True),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            self._created_at_column(),
            self._updated_at_column(),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.ForeignKeyConstraint(
                ["host_id"],
                ["codex_host.host_id"],
                name="fk_codex_workspace_host_id_codex_host",
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["owner_subject_id"],
                ["auth_user.subject_id"],
                name="fk_codex_workspace_owner_subject_id_auth_user",
                ondelete="RESTRICT",
            ),
            sa.PrimaryKeyConstraint("workspace_id", name="pk_codex_workspace"),
            sa.UniqueConstraint(
                "host_id",
                "agent_workspace_key",
                name="uq_codex_workspace_host_agent_workspace_key",
            ),
        )
        op.create_index(
            "ix_codex_workspace_host_enabled", "codex_workspace", ["host_id", "enabled"]
        )
        op.create_index(
            "ix_codex_workspace_owner_updated",
            "codex_workspace",
            ["owner_subject_id", "updated_at"],
        )

    def _create_thread_index_table(self) -> None:
        op.create_table(
            "codex_thread_index",
            sa.Column("thread_index_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("host_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("owner_subject_id", sa.String(128), nullable=False),
            sa.Column("upstream_thread_id", sa.String(256), nullable=False),
            sa.Column("display_name", sa.String(256), nullable=True),
            sa.Column("model", sa.String(128), nullable=True),
            sa.Column("reasoning_effort", sa.String(64), nullable=True),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("active_turn_id", sa.String(256), nullable=True),
            sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("source_kind", sa.String(64), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            self._updated_at_column(),
            sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["host_id"], ["codex_host.host_id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["workspace_id"], ["codex_workspace.workspace_id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["owner_subject_id"], ["auth_user.subject_id"], ondelete="RESTRICT"
            ),
            sa.PrimaryKeyConstraint("thread_index_id", name="pk_codex_thread_index"),
            sa.UniqueConstraint(
                "host_id",
                "upstream_thread_id",
                name="uq_codex_thread_index_host_upstream_thread_id",
            ),
        )
        op.create_index(
            "ix_codex_thread_index_owner_updated",
            "codex_thread_index",
            ["owner_subject_id", "updated_at"],
        )
        op.create_index(
            "ix_codex_thread_index_workspace_archived_updated",
            "codex_thread_index",
            ["workspace_id", "archived", "updated_at"],
        )

    def _create_control_operation_table(self) -> None:
        op.create_table(
            "codex_control_operation",
            sa.Column("operation_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("command_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("actor_subject_id", sa.String(128), nullable=False),
            sa.Column("owner_subject_id", sa.String(128), nullable=False),
            sa.Column("host_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("thread_id", sa.String(256), nullable=True),
            sa.Column("operation_type", sa.String(64), nullable=False),
            sa.Column("idempotency_key", sa.String(256), nullable=False),
            sa.Column("request_digest", sa.String(64), nullable=False),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("dispatch_attempt", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_dispatched_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("ack_deadline_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("error_code", sa.String(128), nullable=True),
            sa.Column("result_digest", sa.String(64), nullable=True),
            sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            self._created_at_column(),
            self._updated_at_column(),
            sa.ForeignKeyConstraint(["host_id"], ["codex_host.host_id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(
                ["workspace_id"], ["codex_workspace.workspace_id"], ondelete="RESTRICT"
            ),
            sa.PrimaryKeyConstraint("operation_id", name="pk_codex_control_operation"),
            sa.UniqueConstraint(
                "actor_subject_id",
                "idempotency_key",
                name="uq_codex_control_operation_actor_idempotency_key",
            ),
            sa.UniqueConstraint(
                "host_id",
                "command_id",
                name="uq_codex_control_operation_host_command_id",
            ),
        )
        op.create_index(
            "ix_codex_control_operation_owner_created",
            "codex_control_operation",
            ["owner_subject_id", "created_at"],
        )
        op.create_index(
            "ix_codex_control_operation_status_created",
            "codex_control_operation",
            ["status", "created_at"],
        )

    def _create_approval_audit_table(self) -> None:
        op.create_table(
            "codex_approval_audit",
            sa.Column("approval_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("owner_subject_id", sa.String(128), nullable=False),
            sa.Column("host_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("thread_id", sa.String(256), nullable=False),
            sa.Column("turn_id", sa.String(256), nullable=True),
            sa.Column("item_id", sa.String(256), nullable=True),
            sa.Column("approval_kind", sa.String(64), nullable=False),
            sa.Column("risk_level", sa.String(32), nullable=False),
            sa.Column("payload_digest", sa.String(64), nullable=False),
            sa.Column("display_summary", postgresql.JSONB(), nullable=False),
            sa.Column("state", sa.String(32), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("decided_by", sa.String(128), nullable=True),
            sa.Column("decision", sa.String(32), nullable=True),
            sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
            self._created_at_column(),
            self._updated_at_column(),
            sa.ForeignKeyConstraint(["host_id"], ["codex_host.host_id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(
                ["workspace_id"], ["codex_workspace.workspace_id"], ondelete="RESTRICT"
            ),
            sa.PrimaryKeyConstraint("approval_id", name="pk_codex_approval_audit"),
        )
        op.create_index(
            "ix_codex_approval_audit_owner_created",
            "codex_approval_audit",
            ["owner_subject_id", "created_at"],
        )
        op.create_index(
            "ix_codex_approval_audit_state_expires", "codex_approval_audit", ["state", "expires_at"]
        )
        op.create_index(
            "ix_codex_approval_audit_thread_created",
            "codex_approval_audit",
            ["thread_id", "created_at"],
        )

    def _insert_scope_rows(self) -> None:
        insert_statement = sa.text(
            """
            INSERT INTO auth_scope (
                scope_code,
                scope_name,
                description,
                scope_kind,
                enabled
            ) VALUES (
                :scope_code,
                :scope_name,
                :description,
                :scope_kind,
                :enabled
            )
            ON CONFLICT (scope_code) DO NOTHING
            """
        )
        for scope_code, scope_name in CODEX_SCOPE_ROWS:
            op.execute(
                insert_statement.bindparams(
                    scope_code=scope_code,
                    scope_name=scope_name,
                    description="Codex 远程控制内置作用域。",
                    scope_kind="builtin",
                    enabled=True,
                )
            )

    def _created_at_column(self) -> sa.Column[datetime]:
        return sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=CURRENT_TIMESTAMP_SQL,
        )

    def _updated_at_column(self) -> sa.Column[datetime]:
        return sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=CURRENT_TIMESTAMP_SQL,
        )


upgrade = Migration().upgrade
downgrade = Migration().downgrade
