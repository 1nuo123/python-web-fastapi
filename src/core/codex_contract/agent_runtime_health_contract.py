"""Agent 诊断结果与退出码契约。"""

from __future__ import annotations

from enum import IntEnum, StrEnum
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

DOCTOR_REASON_CODE_HEALTHY: Final[str] = "healthy"


class AgentDoctorExitCode(IntEnum):
    """doctor 命令的稳定退出码。"""

    HEALTHY = 0
    USER_ACTION_REQUIRED = 10
    COMPATIBILITY_BLOCKED = 20
    NETWORK_FAILURE = 30


class AgentDoctorCheckState(StrEnum):
    """单项诊断状态。"""

    PASS = "pass"
    WARN = "warn"
    BLOCKED = "blocked"
    FAILED = "failed"


class AgentDoctorCheck(BaseModel):
    """已脱敏的诊断检查项。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, max_length=64)
    state: AgentDoctorCheckState
    reason_code: str = Field(min_length=1, max_length=128)
    detail: str | None = Field(default=None, max_length=256)


class AgentDoctorReport(BaseModel):
    """Agent/Codex/控制面诊断汇总。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    agent_version: str = Field(min_length=1, max_length=64)
    codex_version: str | None = Field(default=None, max_length=64)
    schema_digest: str | None = Field(default=None, max_length=128)
    state_database: Path
    checks: tuple[AgentDoctorCheck, ...]
    exit_code: AgentDoctorExitCode
