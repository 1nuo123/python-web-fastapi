"""
任务执行 Outbox ORM 模型模块。
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PostgresqlUuid
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.persistence.sqlalchemy_metadata_registry import (
    AuditTimestampMixin,
    OrmModelBase,
)

TASK_EXECUTION_OUTBOX_TABLE_NAME = "task_execution_outbox"
TASK_EXECUTION_OUTBOX_MESSAGE_ID_UNIQUE_NAME = "uq_task_execution_outbox_message_id"
TASK_EXECUTION_OUTBOX_STATUS_INDEX_NAME = "ix_task_execution_outbox_status"
TASK_EXECUTION_OUTBOX_JOB_KIND_INDEX_NAME = "ix_task_execution_outbox_job_kind"
TASK_EXECUTION_OUTBOX_DEDUPLICATION_KEY_INDEX_NAME = "ix_task_execution_outbox_deduplication_key"
TASK_EXECUTION_OUTBOX_STATUS_RESERVED = "RESERVED"
TASK_EXECUTION_OUTBOX_STATUS_PUBLISHED = "PUBLISHED"
# ``FAILED`` is retained for records written by the pre-retry implementation.
TASK_EXECUTION_OUTBOX_STATUS_FAILED = "FAILED"
TASK_EXECUTION_OUTBOX_STATUS_RETRYING = "RETRYING"
TASK_EXECUTION_OUTBOX_STATUS_UNKNOWN = "UNKNOWN"
TASK_EXECUTION_OUTBOX_STATUS_FAILED_PERMANENT = "FAILED_PERMANENT"
MAX_NAME_LENGTH = 128


class TaskExecutionOutboxStatus(StrEnum):
    """
    任务执行 Outbox 状态枚举。
    """

    RESERVED = TASK_EXECUTION_OUTBOX_STATUS_RESERVED
    PUBLISHED = TASK_EXECUTION_OUTBOX_STATUS_PUBLISHED
    FAILED = TASK_EXECUTION_OUTBOX_STATUS_FAILED
    RETRYING = TASK_EXECUTION_OUTBOX_STATUS_RETRYING
    UNKNOWN = TASK_EXECUTION_OUTBOX_STATUS_UNKNOWN
    FAILED_PERMANENT = TASK_EXECUTION_OUTBOX_STATUS_FAILED_PERMANENT


class TaskExecutionOutboxOrmModel(AuditTimestampMixin, OrmModelBase):
    """
    任务执行 Outbox ORM 模型。
    """

    __tablename__ = TASK_EXECUTION_OUTBOX_TABLE_NAME
    __table_args__ = (
        UniqueConstraint(
            "message_id",
            name=TASK_EXECUTION_OUTBOX_MESSAGE_ID_UNIQUE_NAME,
        ),
        Index(TASK_EXECUTION_OUTBOX_STATUS_INDEX_NAME, "status"),
        Index(TASK_EXECUTION_OUTBOX_JOB_KIND_INDEX_NAME, "job_kind"),
        Index(
            TASK_EXECUTION_OUTBOX_DEDUPLICATION_KEY_INDEX_NAME,
            "deduplication_key",
        ),
    )

    task_execution_outbox_id: Mapped[UUID] = mapped_column(
        PostgresqlUuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    message_id: Mapped[str] = mapped_column(String(MAX_NAME_LENGTH), nullable=False)
    job_kind: Mapped[str] = mapped_column(String(MAX_NAME_LENGTH), nullable=False)
    deduplication_key: Mapped[str] = mapped_column(String(MAX_NAME_LENGTH), nullable=False)
    backend: Mapped[str] = mapped_column(String(MAX_NAME_LENGTH), nullable=False)
    queue_name: Mapped[str] = mapped_column(String(MAX_NAME_LENGTH), nullable=False)
    payload_kind: Mapped[str] = mapped_column(String(MAX_NAME_LENGTH), nullable=False)
    message_json: Mapped[str] = mapped_column(Text(), nullable=False)
    status: Mapped[str] = mapped_column(String(MAX_NAME_LENGTH), nullable=False)
    created_at_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    published_at_epoch: Mapped[int | None] = mapped_column(Integer, nullable=True)
    failed_at_epoch: Mapped[int | None] = mapped_column(Integer, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text(), nullable=True)
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    next_retry_at_epoch: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error_type: Mapped[str | None] = mapped_column(String(MAX_NAME_LENGTH), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text(), nullable=True)
    unknown_at_epoch: Mapped[int | None] = mapped_column(Integer, nullable=True)
    claim_owner: Mapped[str | None] = mapped_column(String(MAX_NAME_LENGTH), nullable=True)
    claimed_at_epoch: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
