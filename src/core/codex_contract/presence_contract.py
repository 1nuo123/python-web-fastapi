"""Codex 主机在线 presence 强类型契约。"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CodexHostPresenceOwner(BaseModel):
    """编码进通用 fenced lease owner 的实例与连接代次。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    instance_id: UUID
    host_id: UUID
    connection_epoch: int = Field(gt=0)
    revocation_generation: int = Field(ge=0)


class CodexHostPresence(BaseModel):
    """控制面可读取的主机 presence。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    owner: CodexHostPresenceOwner
    fencing_token: int = Field(gt=0)
    expires_at: datetime
