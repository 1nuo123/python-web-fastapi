"""Codex Agent 凭据 ORM 模型。"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PostgresqlUuid
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.persistence.sqlalchemy_metadata_registry import OrmModelBase


class CodexAgentCredentialOrmModel(OrmModelBase):
    """只保存设备令牌摘要，不保存设备令牌原文。"""

    __tablename__ = "codex_agent_credential"
    __table_args__ = (
        UniqueConstraint("token_digest", name="uq_codex_agent_credential_token_digest"),
        Index("ix_codex_agent_credential_host_status", "host_id", "status"),
    )

    credential_id: Mapped[UUID] = mapped_column(
        PostgresqlUuid(as_uuid=True), primary_key=True, default=uuid4
    )
    host_id: Mapped[UUID] = mapped_column(
        PostgresqlUuid(as_uuid=True),
        ForeignKey("codex_host.host_id", ondelete="CASCADE"),
        nullable=False,
    )
    token_digest: Mapped[str] = mapped_column(String(128), nullable=False)
    key_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
