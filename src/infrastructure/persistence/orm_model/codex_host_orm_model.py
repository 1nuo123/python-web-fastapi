"""Codex 主机 ORM 模型。"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import JsonValue
from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgresqlUuid
from sqlalchemy.orm import Mapped, mapped_column

from src.core.codex_contract.host_contract import CodexHostCompatibilityState
from src.infrastructure.persistence.database_dialect import DatabaseDialect
from src.infrastructure.persistence.sqlalchemy_metadata_registry import (
    AuditTimestampMixin,
    OrmModelBase,
)

CODEX_HOST_TABLE_NAME = "codex_host"
CODEX_CAPABILITIES_JSON_TYPE = JSON().with_variant(JSONB(), DatabaseDialect.POSTGRESQL)


class CodexHostOrmModel(AuditTimestampMixin, OrmModelBase):
    """主机所有权、版本与能力元数据。"""

    __tablename__ = CODEX_HOST_TABLE_NAME
    __table_args__ = (
        Index("ix_codex_host_owner_revoked", "owner_subject_id", "revoked_at"),
        Index("ix_codex_host_status_last_seen", "status", "last_seen_at"),
    )

    host_id: Mapped[UUID] = mapped_column(
        PostgresqlUuid(as_uuid=True), primary_key=True, default=uuid4
    )
    owner_subject_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("auth_user.subject_id", ondelete="RESTRICT"),
        nullable=False,
    )
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    platform: Mapped[str] = mapped_column(String(64), nullable=False)
    agent_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    codex_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    agent_protocol_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    app_server_schema_digest: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    capabilities: Mapped[dict[str, JsonValue]] = mapped_column(
        CODEX_CAPABILITIES_JSON_TYPE,
        nullable=False,
        default=dict,
    )
    compatibility_state: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=CodexHostCompatibilityState.UNKNOWN.value,
    )
    compatibility_reason_code: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
