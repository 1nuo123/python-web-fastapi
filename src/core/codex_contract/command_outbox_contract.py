"""Codex command outbox 状态与加密记录契约。"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.core.cryptography_contract.aead_envelope_contract import AeadEnvelope

CODEX_COMMAND_KEY_FAMILY = "codex_command_payload"
CODEX_COMMAND_CIPHER_PURPOSE = "codex.command.dispatch"


class CodexCommandOutboxState(StrEnum):
    """命令 outbox 生命周期。"""

    PENDING = "pending"
    CLAIMED = "claimed"
    ROUTED = "routed"
    ACCEPTED = "accepted"
    DEFERRED = "deferred"
    UNKNOWN = "unknown"
    COMPLETED = "completed"
    FAILED = "failed"


class CodexCommandOutboxSnapshot(BaseModel):
    """PostgreSQL 中不含明文命令的 outbox 快照。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    outbox_id: UUID
    operation_id: UUID
    command_id: UUID
    host_id: UUID
    owner_subject_id: str = Field(min_length=1, max_length=128)
    payload: AeadEnvelope
    state: CodexCommandOutboxState
    route_epoch: int | None = Field(default=None, gt=0)
    dispatch_attempt: int = Field(ge=0)
    available_at: datetime
    expires_at: datetime
    claimed_by: str | None = Field(default=None, max_length=128)
    claimed_at: datetime | None = None
    accepted_at: datetime | None = None
    completed_at: datetime | None = None
    last_error_code: str | None = Field(default=None, max_length=128)
    created_at: datetime
    updated_at: datetime
    version: int = Field(ge=1)
