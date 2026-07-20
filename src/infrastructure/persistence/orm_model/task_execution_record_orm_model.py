"""
任务执行记录 ORM 模型模块。
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PostgresqlUuid
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.persistence.sqlalchemy_metadata_registry import (
    AuditTimestampMixin,
    OrmModelBase,
)

TASK_EXECUTION_RECORD_TABLE_NAME = "task_execution_record"
TASK_EXECUTION_RECORD_JOB_KIND_INDEX_NAME = "ix_task_execution_record_job_kind"
TASK_EXECUTION_RECORD_DEDUPLICATION_KEY_INDEX_NAME = "ix_task_execution_record_deduplication_key"
TASK_EXECUTION_RECORD_STATUS_INDEX_NAME = "ix_task_execution_record_status"
TASK_EXECUTION_RECORD_BACKEND_INDEX_NAME = "ix_task_execution_record_backend"
TASK_EXECUTION_RECORD_REQUEST_ID_INDEX_NAME = "ix_task_execution_record_request_id"
TASK_EXECUTION_RECORD_TRACE_ID_INDEX_NAME = "ix_task_execution_record_trace_id"
TASK_EXECUTION_RECORD_QUEUE_NAME_INDEX_NAME = "ix_task_execution_record_queue_name"
TASK_EXECUTION_RECORD_UNIQUE_NAME = "uq_task_execution_record_job_kind_deduplication_key"
TASK_EXECUTION_RECORD_RECORD_ID_UNIQUE_NAME = "uq_task_execution_record_record_id"
MAX_TEXT_LENGTH = 2048
MAX_NAME_LENGTH = 128


class TaskExecutionRecordOrmModel(AuditTimestampMixin, OrmModelBase):
    """
    任务执行记录 ORM 模型。
    """

    __tablename__ = TASK_EXECUTION_RECORD_TABLE_NAME
    __table_args__ = (
        UniqueConstraint(
            "job_kind",
            "deduplication_key",
            name=TASK_EXECUTION_RECORD_UNIQUE_NAME,
        ),
        UniqueConstraint(
            "record_id",
            name=TASK_EXECUTION_RECORD_RECORD_ID_UNIQUE_NAME,
        ),
        Index(TASK_EXECUTION_RECORD_JOB_KIND_INDEX_NAME, "job_kind"),
        Index(TASK_EXECUTION_RECORD_DEDUPLICATION_KEY_INDEX_NAME, "deduplication_key"),
        Index(TASK_EXECUTION_RECORD_STATUS_INDEX_NAME, "status"),
        Index(TASK_EXECUTION_RECORD_BACKEND_INDEX_NAME, "backend"),
        Index(TASK_EXECUTION_RECORD_REQUEST_ID_INDEX_NAME, "request_id"),
        Index(TASK_EXECUTION_RECORD_TRACE_ID_INDEX_NAME, "trace_id"),
        Index(TASK_EXECUTION_RECORD_QUEUE_NAME_INDEX_NAME, "queue_name"),
    )

    task_execution_record_id: Mapped[UUID] = mapped_column(
        PostgresqlUuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    record_id: Mapped[str] = mapped_column(String(MAX_NAME_LENGTH), nullable=False)
    task_id: Mapped[str] = mapped_column(String(MAX_NAME_LENGTH), nullable=False)
    job_kind: Mapped[str] = mapped_column(String(MAX_NAME_LENGTH), nullable=False)
    deduplication_key: Mapped[str] = mapped_column(String(MAX_NAME_LENGTH), nullable=False)
    request_id: Mapped[str] = mapped_column(String(MAX_NAME_LENGTH), nullable=False)
    trace_id: Mapped[str | None] = mapped_column(String(MAX_NAME_LENGTH), nullable=True)
    created_at_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    backend: Mapped[str] = mapped_column(String(MAX_NAME_LENGTH), nullable=False)
    status: Mapped[str] = mapped_column(String(MAX_NAME_LENGTH), nullable=False)
    stage: Mapped[str | None] = mapped_column(String(MAX_NAME_LENGTH), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_retry_at_epoch: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at_epoch: Mapped[int | None] = mapped_column(Integer, nullable=True)
    finished_at_epoch: Mapped[int | None] = mapped_column(Integer, nullable=True)
    failed_at_epoch: Mapped[int | None] = mapped_column(Integer, nullable=True)
    published_at_epoch: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error_type: Mapped[str | None] = mapped_column(String(MAX_NAME_LENGTH), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text(), nullable=True)
    queue_name: Mapped[str | None] = mapped_column(String(MAX_NAME_LENGTH), nullable=True)
    payload_kind: Mapped[str | None] = mapped_column(String(MAX_NAME_LENGTH), nullable=True)
    payload_json: Mapped[str | None] = mapped_column(Text(), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
