"""Codex 浏览器客户端脱敏诊断信封契约。"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

CODEX_CLIENT_DIAGNOSTIC_SCHEMA_VERSION: Final = "1.0"
CLIENT_DIAGNOSTIC_EVENT_ID_PATTERN: Final = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
CLIENT_DIAGNOSTIC_CODE_PATTERN: Final = r"^[a-z][a-z0-9._-]{0,95}$"
CLIENT_DIAGNOSTIC_FINGERPRINT_PATTERN: Final = r"^[a-z][a-z0-9._:-]{0,127}$"


class CodexClientDiagnosticSource(StrEnum):
    """浏览器侧可上报诊断的固定来源枚举。"""

    VUE = "vue"
    WINDOW = "window"
    PROMISE = "promise"
    REQUEST = "request"
    MANUAL = "manual"


class CodexClientDiagnosticSummary(StrEnum):
    """不包含异常正文的固定故障摘要。"""

    VUE_ERROR = "vue_error"
    WINDOW_ERROR = "window_error"
    PROMISE_REJECTION = "promise_rejection"
    REQUEST_FAILURE = "request_failure"
    MANUAL_CAPTURE = "manual_capture"


class CodexClientDiagnosticHeader(BaseModel):
    """客户端诊断的身份、版本和发生时间头。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["client_diagnostic"] = "client_diagnostic"
    schema_version: Literal["1.0"] = CODEX_CLIENT_DIAGNOSTIC_SCHEMA_VERSION
    event_id: str = Field(pattern=CLIENT_DIAGNOSTIC_EVENT_ID_PATTERN)
    source: CodexClientDiagnosticSource
    occurred_at: datetime


class CodexClientDiagnosticDetail(BaseModel):
    """客户端诊断的严格受限载荷，不接受任意异常文本。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["client_diagnostic_detail"] = "client_diagnostic_detail"
    schema_version: Literal["1.0"] = CODEX_CLIENT_DIAGNOSTIC_SCHEMA_VERSION
    summary: CodexClientDiagnosticSummary
    error_code: str = Field(pattern=CLIENT_DIAGNOSTIC_CODE_PATTERN)
    fingerprint: str = Field(pattern=CLIENT_DIAGNOSTIC_FINGERPRINT_PATTERN)


class CodexClientDiagnosticEnvelope(BaseModel):
    """供浏览器与服务端共用的客户端诊断强类型信封。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    header: CodexClientDiagnosticHeader
    detail: CodexClientDiagnosticDetail

    @model_validator(mode="after")
    def validate_schema_version(self) -> Self:
        """拒绝头部与详情版本不一致，避免宽松升级引入敏感字段。"""

        if self.header.schema_version != self.detail.schema_version:
            raise ValueError("客户端诊断头部与详情版本必须一致。")
        return self


class CodexClientDiagnosticReceipt(BaseModel):
    """客户端诊断接收回执，仅说明本实例是否写入安全日志。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    recorded: bool
