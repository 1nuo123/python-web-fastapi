"""按协商能力启用的有界历史窗口，不向旧Agent发送新增字段。"""

from pydantic import BaseModel, ConfigDict, Field


class AgentHistoryWindowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    limit: int = Field(default=50, ge=1, le=200)
    cursor: str | None = Field(default=None, max_length=8192)
    revision: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class AgentHistoryWindowResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    cursor: str | None = Field(default=None, max_length=8192)
    revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    has_more: bool


class AgentHistoryWindowStaleError(ValueError):
    """上游历史已变化，禁止将新旧窗口拼在一起。"""
