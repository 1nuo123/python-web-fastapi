"""
安全 IP 封禁记录 ORM 模型模块。
"""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import Integer, String
from sqlalchemy.dialects.postgresql import UUID as PostgresqlUuid
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.persistence.sqlalchemy_metadata_registry import (
    AuditTimestampMixin,
    OrmModelBase,
)

IP_DIGEST_MAX_LENGTH = 128
IP_BLOCK_REASON_MAX_LENGTH = 64
IP_BLOCK_STATUS_MAX_LENGTH = 32
IP_BLOCK_RELEASED_REASON_MAX_LENGTH = 256


class SecurityIpBlockRecordOrmModel(AuditTimestampMixin, OrmModelBase):
    """
    安全 IP 封禁记录 ORM 模型。
    """

    __tablename__ = "security_ip_block_record"

    record_id: Mapped[UUID] = mapped_column(
        PostgresqlUuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    ip_digest: Mapped[str] = mapped_column(
        String(IP_DIGEST_MAX_LENGTH),
        nullable=False,
        index=True,
    )
    reason: Mapped[str] = mapped_column(
        String(IP_BLOCK_REASON_MAX_LENGTH),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(IP_BLOCK_STATUS_MAX_LENGTH),
        nullable=False,
        index=True,
    )
    blocked_until_epoch: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        index=True,
    )
    released_reason: Mapped[str | None] = mapped_column(
        String(IP_BLOCK_RELEASED_REASON_MAX_LENGTH),
        nullable=True,
    )
