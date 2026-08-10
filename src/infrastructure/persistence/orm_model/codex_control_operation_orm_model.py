"""Codex 控制操作 ORM 模型。"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PostgresqlUuid
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.persistence.sqlalchemy_metadata_registry import (
    AuditTimestampMixin,
    OrmModelBase,
)


class CodexControlOperationOrmModel(AuditTimestampMixin, OrmModelBase):
    """HTTP 幂等受理与 Agent 稳定命令身份元数据。"""

    __tablename__ = "codex_control_operation"
    __table_args__ = (
        UniqueConstraint(
            "actor_subject_id",
            "idempotency_key",
            name="uq_codex_control_operation_actor_idempotency_key",
        ),
        UniqueConstraint(
            "host_id",
            "command_id",
            name="uq_codex_control_operation_host_command_id",
        ),
        Index("ix_codex_control_operation_owner_created", "owner_subject_id", "created_at"),
        Index("ix_codex_control_operation_status_created", "status", "created_at"),
    )

    operation_id: Mapped[UUID] = mapped_column(
        PostgresqlUuid(as_uuid=True), primary_key=True, default=uuid4
    )
    command_id: Mapped[UUID] = mapped_column(PostgresqlUuid(as_uuid=True), nullable=False)
    actor_subject_id: Mapped[str] = mapped_column(String(128), nullable=False)
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
    thread_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    operation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(256), nullable=False)
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    dispatch_attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_dispatched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ack_deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    result_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
