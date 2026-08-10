"""Codex 控制操作契约。"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CodexControlOperationSnapshot(BaseModel):
    """可重投且可审计的控制操作元数据。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    operation_id: UUID
    command_id: UUID
    actor_subject_id: str = Field(min_length=1, max_length=128)
    owner_subject_id: str = Field(min_length=1, max_length=128)
    host_id: UUID
    workspace_id: UUID | None = None
    thread_id: str | None = Field(default=None, max_length=256)
    operation_type: str = Field(min_length=1, max_length=64)
    idempotency_key: str = Field(min_length=1, max_length=256)
    request_digest: str = Field(min_length=64, max_length=64)
    status: str = Field(min_length=1, max_length=32)
    dispatch_attempt: int = Field(ge=0)
    last_dispatched_at: datetime | None = None
    ack_deadline_at: datetime | None = None
    error_code: str | None = Field(default=None, max_length=128)
    result_digest: str | None = Field(default=None, max_length=64)
    accepted_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
