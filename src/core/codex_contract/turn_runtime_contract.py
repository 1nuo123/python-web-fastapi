"""Codex turn 服务端权威运行状态契约。"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class CodexTurnPhase(StrEnum):
    """服务端可观测的 turn 生命周期阶段。"""

    SUBMITTED = "submitted"
    STARTING = "starting"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    STALLED = "stalled"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class CodexTurnRuntime(BaseModel):
    """包含活动时间和租约代次的 turn 权威运行状态。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    turn_id: str = Field(min_length=1, max_length=256)
    thread_id: str = Field(min_length=1, max_length=256)
    phase: CodexTurnPhase
    last_activity_at: datetime
    stalled_reason: str | None = Field(default=None, max_length=512)
    lease_generation: int = Field(ge=0)
    lease_expires_at: datetime | None = None
