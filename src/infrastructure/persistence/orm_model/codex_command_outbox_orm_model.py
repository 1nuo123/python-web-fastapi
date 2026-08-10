"""Codex command outbox ORM 模型。"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, LargeBinary, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PostgresqlUuid
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.persistence.sqlalchemy_metadata_registry import (
    AuditTimestampMixin,
    OrmModelBase,
)

CODEX_COMMAND_OUTBOX_TABLE_NAME = "codex_command_outbox"


class CodexCommandOutboxOrmModel(AuditTimestampMixin, OrmModelBase):
    """只保存 AEAD envelope 和路由状态。"""

    __tablename__ = CODEX_COMMAND_OUTBOX_TABLE_NAME
    __table_args__ = (
        UniqueConstraint("operation_id", name="uq_codex_command_outbox_operation"),
        UniqueConstraint("command_id", name="uq_codex_command_outbox_command"),
        Index("ix_codex_command_outbox_ready", "state", "available_at"),
        Index("ix_codex_command_outbox_host_state", "host_id", "state"),
    )

    outbox_id: Mapped[UUID] = mapped_column(
        PostgresqlUuid(as_uuid=True), primary_key=True, default=uuid4
    )
    operation_id: Mapped[UUID] = mapped_column(
        PostgresqlUuid(as_uuid=True),
        ForeignKey("codex_control_operation.operation_id", ondelete="CASCADE"),
        nullable=False,
    )
    command_id: Mapped[UUID] = mapped_column(PostgresqlUuid(as_uuid=True), nullable=False)
    host_id: Mapped[UUID] = mapped_column(
        PostgresqlUuid(as_uuid=True),
        ForeignKey("codex_host.host_id", ondelete="CASCADE"),
        nullable=False,
    )
    owner_subject_id: Mapped[str] = mapped_column(String(128), nullable=False)
    cipher_algorithm: Mapped[str] = mapped_column(String(64), nullable=False)
    cipher_key_id: Mapped[str] = mapped_column(String(128), nullable=False)
    cipher_nonce: Mapped[bytes] = mapped_column(LargeBinary(12), nullable=False)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary(), nullable=False)
    aad_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    route_epoch: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dispatch_attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    claimed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
