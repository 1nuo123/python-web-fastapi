"""Agent 诊断结果与退出码契约。"""

from __future__ import annotations

from datetime import datetime
from enum import IntEnum, StrEnum
from pathlib import Path
from typing import Final, Literal

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


class AgentRuntimeStatus(BaseModel):
    """Small, redacted runtime report carried in Agent hello.

    The status is an observation only.  Missing fields mean that the check has
    not run in this process/profile; callers must not infer health or write
    capability from an omitted value.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    connection_state: (
        Literal["starting", "connecting", "online", "offline", "blocked", "stopped"] | None
    ) = None
    connection_updated_at: datetime | None = None
    connection_reason: str | None = Field(default=None, max_length=128)
    process_id: int | None = None

    doctor_state: AgentDoctorCheckState | None = None
    doctor_checked_at: datetime | None = None
    doctor_issue_codes: tuple[str, ...] = Field(default=(), max_length=32)
    update_state: str | None = Field(default=None, max_length=32)
    update_checked_at: datetime | None = None
    update_target_version: str | None = Field(default=None, max_length=64)
    update_reason_code: str | None = Field(default=None, max_length=128)

    @classmethod
    def from_doctor_report(
        cls, report: AgentDoctorReport, *, checked_at: datetime
    ) -> AgentRuntimeStatus:
        """Convert a local doctor report without exporting paths or details."""

        state = AgentDoctorCheckState.PASS
        if report.exit_code == AgentDoctorExitCode.NETWORK_FAILURE:
            state = AgentDoctorCheckState.FAILED
        elif report.exit_code == AgentDoctorExitCode.COMPATIBILITY_BLOCKED:
            state = AgentDoctorCheckState.BLOCKED
        elif report.exit_code == AgentDoctorExitCode.USER_ACTION_REQUIRED:
            state = AgentDoctorCheckState.WARN
        issue_codes = tuple(
            check.reason_code
            for check in report.checks
            if check.state is not AgentDoctorCheckState.PASS
        )[:32]
        return cls(
            doctor_state=state,
            doctor_checked_at=checked_at,
            doctor_issue_codes=issue_codes,
        )
