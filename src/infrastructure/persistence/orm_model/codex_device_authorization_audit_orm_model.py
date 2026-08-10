"""Codex 设备授权审计 ORM 模型。"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PostgresqlUuid
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.persistence.sqlalchemy_metadata_registry import OrmModelBase

CODEX_DEVICE_AUTHORIZATION_AUDIT_TABLE_NAME = "codex_device_authorization_audit"


class CodexDeviceAuthorizationAuditOrmModel(OrmModelBase):
    """只保存设备授权决定的稳定审计字段。"""

    __tablename__ = CODEX_DEVICE_AUTHORIZATION_AUDIT_TABLE_NAME
    __table_args__ = (
        UniqueConstraint(
            "enrollment_id",
            "idempotency_key",
            name="uq_codex_device_authorization_audit_idempotency",
        ),
        Index(
            "ix_codex_device_authorization_audit_owner_occurred",
            "owner_subject_id",
            "occurred_at",
        ),
    )

    audit_id: Mapped[UUID] = mapped_column(
        PostgresqlUuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    enrollment_id: Mapped[UUID] = mapped_column(
        PostgresqlUuid(as_uuid=True),
        nullable=False,
    )
    host_id: Mapped[UUID | None] = mapped_column(
        PostgresqlUuid(as_uuid=True),
        ForeignKey("codex_host.host_id", ondelete="SET NULL"),
        nullable=True,
    )
    owner_subject_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("auth_user.subject_id", ondelete="RESTRICT"),
        nullable=False,
    )
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
