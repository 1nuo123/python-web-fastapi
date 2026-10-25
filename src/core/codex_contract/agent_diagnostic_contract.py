"""Codex Agent 脱敏诊断事件契约。"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

AGENT_DIAGNOSTIC_SCHEMA_VERSION: Final = "1.0"
AGENT_DIAGNOSTIC_DIGEST_PATTERN: Final = r"^[0-9a-f]{16}$"


class AgentDiagnosticCode(StrEnum):
    """Agent 可长期检索的稳定诊断码。"""

    CONNECTION_ENDED = "agent.connection.ended"
    CONNECTION_RECOVERED = "agent.connection.recovered"
    EXECUTION_STOPPED = "agent.execution.stopped"
    APP_SERVER_STDERR = "agent.app_server.stderr"
    APP_SERVER_STDERR_TOO_LONG = "agent.app_server.stderr_too_long"
    APP_SERVER_PROTOCOL_WARNING = "agent.app_server.protocol_warning"
    APP_SERVER_EXIT_NON_ZERO = "agent.app_server.exit_non_zero"


class AgentDiagnosticHeader(BaseModel):
    """所有 Agent 诊断共享的进程定位头。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["agent_diagnostic"] = "agent_diagnostic"
    schema_version: Literal["1.0"] = AGENT_DIAGNOSTIC_SCHEMA_VERSION
    detail_kind: AgentDiagnosticCode
    host_id: str = Field(min_length=1, max_length=128)
    app_server_instance_id: str = Field(min_length=1, max_length=128)
    process_id: int | None = Field(default=None, ge=1)
    codex_version: str | None = Field(default=None, min_length=1, max_length=64)
    occurred_at: datetime


class AgentStderrDiagnosticDetail(BaseModel):
    """不包含 stderr 原文的行级摘要。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal[
        "agent.app_server.stderr",
        "agent.app_server.stderr_too_long",
    ]
    schema_version: Literal["1.0"] = AGENT_DIAGNOSTIC_SCHEMA_VERSION
    line_number: int = Field(ge=1)
    byte_count: int = Field(ge=0)
    digest: str | None = Field(default=None, pattern=AGENT_DIAGNOSTIC_DIGEST_PATTERN)


class AgentProtocolWarningDiagnosticDetail(BaseModel):
    """JSON-RPC 协议损坏或不兼容的脱敏摘要。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["agent.app_server.protocol_warning"] = "agent.app_server.protocol_warning"
    schema_version: Literal["1.0"] = AGENT_DIAGNOSTIC_SCHEMA_VERSION
    byte_count: int = Field(ge=0)
    digest: str = Field(pattern=AGENT_DIAGNOSTIC_DIGEST_PATTERN)
    reason_code: str = Field(default="app_server_protocol_warning", min_length=1, max_length=128)
    method: str | None = Field(default=None, max_length=128)
    count: int = Field(default=1, ge=1)


class AgentProcessExitDiagnosticDetail(BaseModel):
    """App Server 非零退出摘要。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["agent.app_server.exit_non_zero"] = "agent.app_server.exit_non_zero"
    schema_version: Literal["1.0"] = AGENT_DIAGNOSTIC_SCHEMA_VERSION
    exit_code: int


class AgentLifecycleDiagnosticDetail(BaseModel):
    """连接/执行生命周期事实，不包含凭据、URL或业务正文。"""

    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["agent.connection.ended", "agent.connection.recovered", "agent.execution.stopped"]
    schema_version: Literal["1.0"] = AGENT_DIAGNOSTIC_SCHEMA_VERSION
    attempt_id: str
    epoch: int | None
    phase: str
    reason_code: str
    duration_seconds: float = Field(ge=0)
    remaining_lease_seconds: float = Field(ge=0)
    execution_preserved: bool


AgentDiagnosticDetail = Annotated[
    AgentStderrDiagnosticDetail
    | AgentProtocolWarningDiagnosticDetail
    | AgentProcessExitDiagnosticDetail
    | AgentLifecycleDiagnosticDetail,
    Field(discriminator="kind"),
]


class AgentDiagnosticEnvelope(BaseModel):
    """公共诊断头与强类型扩展字段信封。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    header: AgentDiagnosticHeader
    detail: AgentDiagnosticDetail

    @model_validator(mode="after")
    def validate_detail_identity(self) -> Self:
        """诊断头与扩展字段必须属于同一类型和版本。"""

        if self.header.detail_kind.value != self.detail.kind:
            raise ValueError("Agent诊断头与扩展类型不一致。")
        if self.header.schema_version != self.detail.schema_version:
            raise ValueError("Agent诊断头与扩展版本不一致。")
        return self

    def to_log_line(self) -> str:
        """生成不含敏感正文的中文 key=value 单行。"""

        fields = {
            "诊断码": self.header.detail_kind.value,
            "host_id": self.header.host_id,
            "App_Server代次": self.header.app_server_instance_id,
            "PID": self.header.process_id,
            "Codex版本": self.header.codex_version,
            "发生时间": self.header.occurred_at.isoformat(),
            **self.detail.model_dump(exclude={"kind", "schema_version"}),
        }
        return "Agent诊断 " + " ".join(
            f"{key}={value}" for key, value in fields.items() if value is not None
        )
