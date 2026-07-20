"""
管理员日志查询应用端口。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal, Protocol

from pydantic import BaseModel, ConfigDict

from src.core.logging_contract.log_event_contract import (
    LogDetailUnion,
    LogEventKind,
    LogLevel,
)
from src.core.security_contract.security_event_contract import (
    SecurityEventDecision,
    SecurityEventEnvelope,
    SecurityEventSeverity,
    SecurityEventType,
)

ADMIN_UNPARSED_LOG_DETAIL_KIND: Final = "admin_unparsed_log_detail"
ADMIN_LOG_QUERY_SCHEMA_VERSION: Final = "1.0"


class AdminUnparsedLogDetail(BaseModel):
    """
    管理员日志不可解析详情摘要。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["admin_unparsed_log_detail"] = ADMIN_UNPARSED_LOG_DETAIL_KIND
    schema_version: Literal["1.0"] = ADMIN_LOG_QUERY_SCHEMA_VERSION
    summary: str


@dataclass(slots=True)
class AdminLogRecordFilter:
    """
    管理员日志查询过滤条件。
    """

    level: LogLevel | None
    event_kind: LogEventKind | None
    request_id: str | None
    trace_id: str | None
    occurred_from: datetime | None
    occurred_to: datetime | None
    limit: int


@dataclass(slots=True)
class AdminSecurityEventFilter:
    """
    管理员安全事件查询过滤条件。
    """

    event_type: SecurityEventType | None
    severity: SecurityEventSeverity | None
    decision: SecurityEventDecision | None
    occurred_from: datetime | None
    occurred_to: datetime | None
    limit: int


@dataclass(slots=True)
class AdminLogRecordSnapshot:
    """
    管理员日志记录快照。
    """

    event_id: str
    event_kind: LogEventKind
    schema_version: str
    level: LogLevel
    message: str
    occurred_at: datetime
    request_id: str | None
    trace_id: str | None
    authenticated_subject_id: str | None
    source_module: str
    source_component: str
    detail: LogDetailUnion | AdminUnparsedLogDetail
    security_event: SecurityEventEnvelope | None


class AdminLogQueryPort(Protocol):
    """
    管理员日志查询端口。
    """

    def list_admin_log_records(
        self,
        query_filter: AdminLogRecordFilter,
    ) -> list[AdminLogRecordSnapshot]:
        """
        查询应用日志记录。
        """

    def list_admin_security_events(
        self,
        query_filter: AdminSecurityEventFilter,
    ) -> list[AdminLogRecordSnapshot]:
        """
        查询安全事件记录。
        """
