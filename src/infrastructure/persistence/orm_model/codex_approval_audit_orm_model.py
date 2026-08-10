"""Codex 审批审计 ORM 模型。"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import JsonValue
from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgresqlUuid
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.persistence.database_dialect import DatabaseDialect
from src.infrastructure.persistence.sqlalchemy_metadata_registry import (
    AuditTimestampMixin,
    OrmModelBase,
)

CODEX_APPROVAL_SUMMARY_JSON_TYPE = JSON().with_variant(
    JSONB(),
    DatabaseDialect.POSTGRESQL,
)


class CodexApprovalAuditOrmModel(AuditTimestampMixin, OrmModelBase):
    """审批状态与脱敏展示摘要。"""

    __tablename__ = "codex_approval_audit"
    __table_args__ = (
        Index("ix_codex_approval_audit_owner_created", "owner_subject_id", "created_at"),
        Index("ix_codex_approval_audit_state_expires", "state", "expires_at"),
        Index("ix_codex_approval_audit_thread_created", "thread_id", "created_at"),
    )

    approval_id: Mapped[UUID] = mapped_column(
        PostgresqlUuid(as_uuid=True), primary_key=True, default=uuid4
    )
    owner_subject_id: Mapped[str] = mapped_column(String(128), nullable=False)
    host_id: Mapped[UUID] = mapped_column(
        PostgresqlUuid(as_uuid=True),
        ForeignKey("codex_host.host_id", ondelete="RESTRICT"),
        nullable=False,
    )
    workspace_id: Mapped[UUID | None] = mapped_column(
        PostgresqlUuid(as_uuid=True),
        ForeignKey("codex_workspace.workspace_id", ondelete="RESTRICT"),
        nullable=True,
    )
    thread_id: Mapped[str] = mapped_column(String(256), nullable=False)
    turn_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    item_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    approval_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(32), nullable=False)
    payload_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    display_summary: Mapped[dict[str, JsonValue]] = mapped_column(
        CODEX_APPROVAL_SUMMARY_JSON_TYPE,
        nullable=False,
    )
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    decision: Mapped[str | None] = mapped_column(String(32), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
