"""Codex Agent 事件累计确认游标契约。"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CodexAgentEventCursorState(BaseModel):
    """原子状态公共头内承载的强类型 Agent 事件游标。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    host_id: UUID
    agent_event_epoch: UUID
    after_seq: int = Field(ge=0)
