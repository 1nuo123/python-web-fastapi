"""Agent 命令投递与本地去重账本契约。"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class AgentCommandJournalState(StrEnum):
    """Agent命令在本地持久账本中的状态。"""

    RECEIVED = "received"
    EXECUTING = "executing"
    ACCEPTED = "accepted"
    COMPLETED = "completed"
    FAILED = "failed"
    UNKNOWN = "unknown"


class AgentCommandClaimKind(StrEnum):
    """命令登记结果。"""

    NEW = "new"
    REPLAY = "replay"


class AgentCommandIdentity(BaseModel):
    """控制面重投时必须保持稳定的命令身份。"""

    model_config = ConfigDict(extra="forbid")

    command_id: str = Field(min_length=1)
    operation_id: str = Field(min_length=1)
    command_type: str = Field(min_length=1)
    request_digest: str = Field(min_length=1)


class AgentCommandResultSummary(BaseModel):
    """不含prompt、代码和终端正文的命令结果摘要。"""

    model_config = ConfigDict(extra="forbid")

    outcome_code: str = Field(min_length=1)
    upstream_thread_id: str | None = None
    upstream_turn_id: str | None = None


class AgentCommandJournalRecord(BaseModel):
    """Agent命令账本中的持久记录。"""

    model_config = ConfigDict(extra="forbid")

    identity: AgentCommandIdentity
    state: AgentCommandJournalState
    result_summary: AgentCommandResultSummary | None
    created_at_epoch: float
    updated_at_epoch: float


class AgentCommandClaim(BaseModel):
    """命令首次登记或重复命中的结果。"""

    model_config = ConfigDict(extra="forbid")

    kind: AgentCommandClaimKind
    record: AgentCommandJournalRecord
