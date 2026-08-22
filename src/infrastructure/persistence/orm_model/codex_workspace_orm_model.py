"""Codex 工作区 ORM 模型。"""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import JSON, Boolean, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PostgresqlUuid
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.persistence.sqlalchemy_metadata_registry import (
    AuditTimestampMixin,
    OrmModelBase,
)


class CodexWorkspaceOrmModel(AuditTimestampMixin, OrmModelBase):
    """Agent 本地工作区登记项的控制面索引。"""

    __tablename__ = "codex_workspace"
    __table_args__ = (
        UniqueConstraint(
            "host_id",
            "agent_workspace_key",
            name="uq_codex_workspace_host_agent_workspace_key",
        ),
        Index("ix_codex_workspace_host_enabled", "host_id", "enabled"),
        Index("ix_codex_workspace_owner_updated", "owner_subject_id", "updated_at"),
        Index(
            "ix_codex_workspace_owner_pin_order",
            "owner_subject_id",
            "is_pinned",
            "updated_at",
            "workspace_id",
        ),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        PostgresqlUuid(as_uuid=True), primary_key=True, default=uuid4
    )
    host_id: Mapped[UUID] = mapped_column(
        PostgresqlUuid(as_uuid=True),
        ForeignKey("codex_host.host_id", ondelete="CASCADE"),
        nullable=False,
    )
    owner_subject_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("auth_user.subject_id", ondelete="RESTRICT"),
        nullable=False,
    )
    agent_workspace_key: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    repo_fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True)
    default_branch: Mapped[str | None] = mapped_column(String(256), nullable=True)
    worktree_policy: Mapped[dict[str, object]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    execution_preferences: Mapped[dict[str, object]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    is_pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
