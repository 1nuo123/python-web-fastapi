"""
日志写入契约模块。
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from src.core.logging_contract.log_event_contract import LogEventEnvelope

LOG_WRITE_SCHEMA_VERSION = "1.0"
LOG_WRITE_REQUEST_KIND = "log_write_request"
LOG_WRITE_RESULT_KIND = "log_write_result"


class LogWriteReason(StrEnum):
    """
    日志刷盘触发原因枚举。
    """

    BUFFER_LIMIT = "buffer_limit"
    INTERVAL = "interval"
    SHUTDOWN = "shutdown"
    MANUAL = "manual"


class LogWriteRequest(BaseModel):
    """
    日志写入请求模型。
    """

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(default=LOG_WRITE_REQUEST_KIND)
    schema_version: str = Field(default=LOG_WRITE_SCHEMA_VERSION)
    reason: LogWriteReason
    events: list[LogEventEnvelope]


class LogWriteResult(BaseModel):
    """
    日志写入结果模型。
    """

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(default=LOG_WRITE_RESULT_KIND)
    schema_version: str = Field(default=LOG_WRITE_SCHEMA_VERSION)
    written_count: int
    failed_count: int
    degraded_to_stdout: bool
    failure_reason: str | None = None
