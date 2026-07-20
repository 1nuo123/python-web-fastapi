"""
密钥环快照 ORM 模型模块。
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PostgresqlUuid
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.persistence.sqlalchemy_metadata_registry import (
    AuditTimestampMixin,
    OrmModelBase,
)

KEY_RING_SNAPSHOT_TABLE_NAME = "key_ring_snapshot"
KEY_RING_SNAPSHOT_FAMILY_UNIQUE_NAME = "uq_key_ring_snapshot_key_family"
KEY_RING_SNAPSHOT_FAMILY_INDEX_NAME = "ix_key_ring_snapshot_key_family"
KEY_RING_SNAPSHOT_VERSION_INDEX_NAME = "ix_key_ring_snapshot_version_digest"
MAX_KEY_FAMILY_LENGTH = 128
VERSION_DIGEST_LENGTH = 64


class KeyRingSnapshotOrmModel(AuditTimestampMixin, OrmModelBase):
    """
    密钥环快照 ORM 模型。
    """

    __tablename__ = KEY_RING_SNAPSHOT_TABLE_NAME
    __table_args__ = (
        UniqueConstraint(
            "key_family",
            name=KEY_RING_SNAPSHOT_FAMILY_UNIQUE_NAME,
        ),
        Index(KEY_RING_SNAPSHOT_FAMILY_INDEX_NAME, "key_family"),
        Index(KEY_RING_SNAPSHOT_VERSION_INDEX_NAME, "version_digest"),
    )

    key_ring_snapshot_id: Mapped[UUID] = mapped_column(
        PostgresqlUuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    key_family: Mapped[str] = mapped_column(
        String(MAX_KEY_FAMILY_LENGTH),
        nullable=False,
    )
    encrypted_snapshot_json: Mapped[str] = mapped_column(Text(), nullable=False)
    version_digest: Mapped[str] = mapped_column(
        String(VERSION_DIGEST_LENGTH),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
