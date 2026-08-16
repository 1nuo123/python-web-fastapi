"""Codex 主机设备公钥 ORM 模型。"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PostgresqlUuid
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.persistence.sqlalchemy_metadata_registry import (
    AuditTimestampMixin,
    OrmModelBase,
)

CODEX_HOST_DEVICE_KEY_TABLE_NAME = "codex_host_device_key"


class CodexHostDeviceKeyOrmModel(AuditTimestampMixin, OrmModelBase):
    """设备公钥、指纹、代次与撤销字段。"""

    __tablename__ = CODEX_HOST_DEVICE_KEY_TABLE_NAME
    __table_args__ = (
        UniqueConstraint("enrollment_id", name="uq_codex_host_device_key_enrollment"),
        UniqueConstraint(
            "host_id", "fingerprint", name="uq_codex_host_device_key_host_fingerprint"
        ),
        Index("ix_codex_host_device_key_host_state", "host_id", "state"),
        Index(
            "uq_codex_host_device_key_active_fingerprint",
            "fingerprint",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

    key_id: Mapped[UUID] = mapped_column(
        PostgresqlUuid(as_uuid=True), primary_key=True, default=uuid4
    )
    enrollment_id: Mapped[UUID] = mapped_column(PostgresqlUuid(as_uuid=True), nullable=False)
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
    public_key: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retire_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
