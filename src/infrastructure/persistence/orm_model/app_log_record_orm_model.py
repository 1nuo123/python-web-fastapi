"""
应用日志 ORM 模型模块。
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgresqlUuid
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.persistence.database_dialect import DatabaseDialect
from src.infrastructure.persistence.sqlalchemy_metadata_registry import (
    AuditTimestampMixin,
    OrmModelBase,
)

APP_LOG_RECORD_TABLE_NAME = "app_log_record"
APP_LOG_EVENT_KIND_INDEX_NAME = "ix_app_log_record_event_kind"
APP_LOG_OCCURRED_AT_INDEX_NAME = "ix_app_log_record_occurred_at"
APP_LOG_REQUEST_ID_INDEX_NAME = "ix_app_log_record_request_id"
APP_LOG_TRACE_ID_INDEX_NAME = "ix_app_log_record_trace_id"
APP_LOG_LEVEL_INDEX_NAME = "ix_app_log_record_level"
EVENT_ID_MAX_LENGTH = 128
SCHEMA_VERSION_MAX_LENGTH = 64
KIND_MAX_LENGTH = 64
LEVEL_MAX_LENGTH = 16
SOURCE_MODULE_MAX_LENGTH = 128
SOURCE_COMPONENT_MAX_LENGTH = 128
REQUEST_ID_MAX_LENGTH = 128
TRACE_ID_MAX_LENGTH = 128
SUBJECT_ID_MAX_LENGTH = 128
APP_LOG_DETAIL_JSON_TYPE = JSON().with_variant(JSONB(), DatabaseDialect.POSTGRESQL)


class AppLogRecordOrmModel(AuditTimestampMixin, OrmModelBase):
    """
    应用日志 ORM 模型。
    """

    __tablename__ = APP_LOG_RECORD_TABLE_NAME
    __table_args__ = (
        Index(APP_LOG_OCCURRED_AT_INDEX_NAME, "occurred_at"),
        Index(APP_LOG_EVENT_KIND_INDEX_NAME, "event_kind"),
        Index(APP_LOG_REQUEST_ID_INDEX_NAME, "request_id"),
        Index(APP_LOG_TRACE_ID_INDEX_NAME, "trace_id"),
        Index(APP_LOG_LEVEL_INDEX_NAME, "level"),
    )

    log_record_id: Mapped[UUID] = mapped_column(
        PostgresqlUuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    event_id: Mapped[str] = mapped_column(
        String(EVENT_ID_MAX_LENGTH),
        nullable=False,
        unique=True,
    )
    event_kind: Mapped[str] = mapped_column(
        String(KIND_MAX_LENGTH),
        nullable=False,
    )
    schema_version: Mapped[str] = mapped_column(
        String(SCHEMA_VERSION_MAX_LENGTH),
        nullable=False,
    )
    level: Mapped[str] = mapped_column(
        String(LEVEL_MAX_LENGTH),
        nullable=False,
    )
    message: Mapped[str] = mapped_column(Text(), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    request_id: Mapped[str | None] = mapped_column(
        String(REQUEST_ID_MAX_LENGTH),
        nullable=True,
    )
    trace_id: Mapped[str | None] = mapped_column(
        String(TRACE_ID_MAX_LENGTH),
        nullable=True,
    )
    authenticated_subject_id: Mapped[str | None] = mapped_column(
        String(SUBJECT_ID_MAX_LENGTH),
        nullable=True,
    )
    source_module: Mapped[str] = mapped_column(
        String(SOURCE_MODULE_MAX_LENGTH),
        nullable=False,
    )
    source_component: Mapped[str] = mapped_column(
        String(SOURCE_COMPONENT_MAX_LENGTH),
        nullable=False,
    )
    detail_json: Mapped[dict[str, object]] = mapped_column(
        APP_LOG_DETAIL_JSON_TYPE,
        nullable=False,
    )
