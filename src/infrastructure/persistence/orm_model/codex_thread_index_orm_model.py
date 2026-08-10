"""Codex 线程索引 ORM 模型。"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PostgresqlUuid
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.persistence.sqlalchemy_metadata_registry import OrmModelBase


class CodexThreadIndexOrmModel(OrmModelBase):
    """线程检索元数据；对话正文仍以 App Server 为事实源。"""

    __tablename__ = "codex_thread_index"
    __table_args__ = (
        UniqueConstraint(
            "host_id",
            "upstream_thread_id",
            name="uq_codex_thread_index_host_upstream_thread_id",
        ),
        Index("ix_codex_thread_index_owner_updated", "owner_subject_id", "updated_at"),
        Index(
            "ix_codex_thread_index_workspace_archived_updated",
            "workspace_id",
            "archived",
            "updated_at",
        ),
    )

    thread_index_id: Mapped[UUID] = mapped_column(
        PostgresqlUuid(as_uuid=True), primary_key=True, default=uuid4
    )
    host_id: Mapped[UUID] = mapped_column(
        PostgresqlUuid(as_uuid=True),
        ForeignKey("codex_host.host_id", ondelete="CASCADE"),
        nullable=False,
    )
    workspace_id: Mapped[UUID] = mapped_column(
        PostgresqlUuid(as_uuid=True),
        ForeignKey("codex_workspace.workspace_id", ondelete="CASCADE"),
        nullable=False,
    )
    owner_subject_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("auth_user.subject_id", ondelete="RESTRICT"),
        nullable=False,
    )
    upstream_thread_id: Mapped[str] = mapped_column(String(256), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reasoning_effort: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    active_turn_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_kind: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    last_synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
