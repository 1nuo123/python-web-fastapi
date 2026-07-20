"""
日志记录仓储实现模块。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from src.core.logging_contract.log_event_contract import LogEventKind, LogLevel
from src.core.persistence_contract.repository_contract import Repository
from src.core.security_contract.security_event_contract import (
    SecurityEventDecision,
    SecurityEventSeverity,
    SecurityEventType,
)
from src.infrastructure.persistence.orm_model.app_log_record_orm_model import (
    AppLogRecordOrmModel,
)

LOG_RECORD_QUERY_LIMIT_MINIMUM = 1
LOG_RECORD_QUERY_LIMIT_MAXIMUM = 200
LOG_DETAIL_SECURITY_EVENT_FIELD = "security_event"
LOG_DETAIL_KIND_FIELD = "kind"
LOG_DETAIL_SECURITY_KIND = "security"
SECURITY_EVENT_HEADER_FIELD = "header"
SECURITY_EVENT_DETAIL_FIELD = "detail"
SECURITY_EVENT_TYPE_FIELD = "event_type"
SECURITY_EVENT_SEVERITY_FIELD = "severity"
SECURITY_EVENT_DECISION_FIELD = "decision"
SECURITY_EVENT_DETAIL_KIND_FIELD = "detail_kind"
SECURITY_EVENT_SUBJECT_ID_FIELD = "subject_id"
BUSINESS_AUDIT_OPERATION_NAME_FIELD = "operation_name"
BUSINESS_AUDIT_TARGET_KIND_FIELD = "target_kind"
BUSINESS_AUDIT_TARGET_ID_FIELD = "target_id"
BUSINESS_AUDIT_ACTOR_SUBJECT_ID_FIELD = "actor_subject_id"
ADMIN_IDENTITY_SECURITY_EVENT_DETAIL_KIND = "admin_identity_security_event"


class LogRecordRepositoryImpl(Repository):
    """
    日志记录仓储实现。
    """

    def __init__(self, session: Session) -> None:
        """
        初始化日志记录仓储实现。

        :param session: 数据库会话。
        :type session: Session
        :returns: 无返回值。
        :rtype: None
        """

        self._session = session

    def ping(self) -> bool:
        """
        探测日志仓储依赖是否可用。

        :returns: ``True`` 表示当前数据库会话可执行基础查询。
        :rtype: bool
        """

        self._session.execute(select(1))
        return True

    def add_records(self, records: list[AppLogRecordOrmModel]) -> None:
        """
        批量新增日志记录。

        :param records: 待持久化的日志记录列表。
        :type records: list[AppLogRecordOrmModel]
        :returns: 无返回值。
        :rtype: None
        """

        self._session.add_all(records)

    def list_records(
        self,
        *,
        limit: int,
        level: LogLevel | None = None,
        event_kind: LogEventKind | None = None,
        request_id: str | None = None,
        trace_id: str | None = None,
        occurred_from: datetime | None = None,
        occurred_to: datetime | None = None,
        security_event_type: SecurityEventType | None = None,
        security_event_severity: SecurityEventSeverity | None = None,
        security_event_decision: SecurityEventDecision | None = None,
    ) -> list[AppLogRecordOrmModel]:
        """
        查询应用日志记录。
        """

        statement: Select[tuple[AppLogRecordOrmModel]] = (
            select(AppLogRecordOrmModel)
            .order_by(
                AppLogRecordOrmModel.occurred_at.desc(),
                AppLogRecordOrmModel.log_record_id.desc(),
            )
            .limit(self._normalize_limit(limit))
        )
        if level is not None:
            statement = statement.where(AppLogRecordOrmModel.level == level.value)
        if event_kind is not None:
            statement = statement.where(AppLogRecordOrmModel.event_kind == event_kind.value)
        if request_id is not None:
            statement = statement.where(AppLogRecordOrmModel.request_id == request_id)
        if trace_id is not None:
            statement = statement.where(AppLogRecordOrmModel.trace_id == trace_id)
        if occurred_from is not None:
            statement = statement.where(AppLogRecordOrmModel.occurred_at >= occurred_from)
        if occurred_to is not None:
            statement = statement.where(AppLogRecordOrmModel.occurred_at <= occurred_to)
        if security_event_type is not None:
            statement = statement.where(
                AppLogRecordOrmModel.detail_json[
                    (
                        LOG_DETAIL_SECURITY_EVENT_FIELD,
                        SECURITY_EVENT_HEADER_FIELD,
                        SECURITY_EVENT_TYPE_FIELD,
                    )
                ].as_string()
                == security_event_type.value
            )
        if security_event_severity is not None:
            statement = statement.where(
                AppLogRecordOrmModel.detail_json[
                    (
                        LOG_DETAIL_SECURITY_EVENT_FIELD,
                        SECURITY_EVENT_HEADER_FIELD,
                        SECURITY_EVENT_SEVERITY_FIELD,
                    )
                ].as_string()
                == security_event_severity.value
            )
        if security_event_decision is not None:
            statement = statement.where(
                AppLogRecordOrmModel.detail_json[
                    (
                        LOG_DETAIL_SECURITY_EVENT_FIELD,
                        SECURITY_EVENT_HEADER_FIELD,
                        SECURITY_EVENT_DECISION_FIELD,
                    )
                ].as_string()
                == security_event_decision.value
            )
        return list(self._session.execute(statement).scalars().all())

    def list_business_audit_records(
        self,
        *,
        page_size: int,
        offset: int,
        operation_names: list[str] | None,
        actor_subject_id: str | None,
        target_kind: str | None,
        target_id: str | None,
        occurred_from: datetime | None,
        occurred_to: datetime | None,
    ) -> list[AppLogRecordOrmModel]:
        """
        查询业务审计日志记录。
        """

        statement = (
            self._build_business_audit_statement(
                operation_names=operation_names,
                actor_subject_id=actor_subject_id,
                target_kind=target_kind,
                target_id=target_id,
                occurred_from=occurred_from,
                occurred_to=occurred_to,
            )
            .order_by(
                AppLogRecordOrmModel.occurred_at.desc(),
                AppLogRecordOrmModel.log_record_id.desc(),
            )
            .offset(max(offset, 0))
            .limit(self._normalize_limit(page_size))
        )
        return list(self._session.execute(statement).scalars().all())

    def count_business_audit_records(
        self,
        *,
        operation_names: list[str] | None,
        actor_subject_id: str | None,
        target_kind: str | None,
        target_id: str | None,
        occurred_from: datetime | None,
        occurred_to: datetime | None,
    ) -> int:
        """
        统计业务审计日志记录。
        """

        statement = self._build_business_audit_statement(
            operation_names=operation_names,
            actor_subject_id=actor_subject_id,
            target_kind=target_kind,
            target_id=target_id,
            occurred_from=occurred_from,
            occurred_to=occurred_to,
        )
        count_statement = self._build_business_audit_count_statement(statement)
        return int(self._session.execute(count_statement).scalar_one())

    def _build_business_audit_count_statement(
        self,
        statement: Select[tuple[AppLogRecordOrmModel]],
    ) -> Select[tuple[int]]:
        """
        构建业务审计统计语句。

        :param statement: 已下推过滤的业务审计查询语句。
        :type statement: Select[tuple[AppLogRecordOrmModel]]
        :returns: 业务审计统计语句。
        :rtype: Select[tuple[int]]
        """

        return select(func.count()).select_from(statement.subquery())

    def _normalize_limit(self, limit: int) -> int:
        """
        归一化日志查询条数。
        """

        if limit < LOG_RECORD_QUERY_LIMIT_MINIMUM:
            return LOG_RECORD_QUERY_LIMIT_MINIMUM
        return min(limit, LOG_RECORD_QUERY_LIMIT_MAXIMUM)

    def _build_business_audit_statement(
        self,
        *,
        operation_names: list[str] | None,
        actor_subject_id: str | None,
        target_kind: str | None,
        target_id: str | None,
        occurred_from: datetime | None,
        occurred_to: datetime | None,
    ) -> Select[tuple[AppLogRecordOrmModel]]:
        """
        构建业务审计查询语句。
        """

        statement: Select[tuple[AppLogRecordOrmModel]] = select(AppLogRecordOrmModel)
        statement = statement.where(
            AppLogRecordOrmModel.event_kind == LogEventKind.SECURITY.value,
            AppLogRecordOrmModel.detail_json[LOG_DETAIL_KIND_FIELD].as_string()
            == LOG_DETAIL_SECURITY_KIND,
            AppLogRecordOrmModel.detail_json[
                (
                    LOG_DETAIL_SECURITY_EVENT_FIELD,
                    SECURITY_EVENT_HEADER_FIELD,
                    SECURITY_EVENT_DETAIL_KIND_FIELD,
                )
            ].as_string()
            == ADMIN_IDENTITY_SECURITY_EVENT_DETAIL_KIND,
        )
        if operation_names is not None:
            statement = statement.where(
                AppLogRecordOrmModel.detail_json[
                    (
                        LOG_DETAIL_SECURITY_EVENT_FIELD,
                        SECURITY_EVENT_DETAIL_FIELD,
                        BUSINESS_AUDIT_OPERATION_NAME_FIELD,
                    )
                ]
                .as_string()
                .in_(operation_names)
            )
        if actor_subject_id is not None:
            statement = statement.where(
                AppLogRecordOrmModel.detail_json[
                    (
                        LOG_DETAIL_SECURITY_EVENT_FIELD,
                        SECURITY_EVENT_DETAIL_FIELD,
                        BUSINESS_AUDIT_ACTOR_SUBJECT_ID_FIELD,
                    )
                ].as_string()
                == actor_subject_id
            )
        if target_kind is not None:
            statement = statement.where(
                AppLogRecordOrmModel.detail_json[
                    (
                        LOG_DETAIL_SECURITY_EVENT_FIELD,
                        SECURITY_EVENT_DETAIL_FIELD,
                        BUSINESS_AUDIT_TARGET_KIND_FIELD,
                    )
                ].as_string()
                == target_kind
            )
        if target_id is not None:
            statement = statement.where(
                AppLogRecordOrmModel.detail_json[
                    (
                        LOG_DETAIL_SECURITY_EVENT_FIELD,
                        SECURITY_EVENT_DETAIL_FIELD,
                        BUSINESS_AUDIT_TARGET_ID_FIELD,
                    )
                ].as_string()
                == target_id
            )
        if occurred_from is not None:
            statement = statement.where(AppLogRecordOrmModel.occurred_at >= occurred_from)
        if occurred_to is not None:
            statement = statement.where(AppLogRecordOrmModel.occurred_at <= occurred_to)
        return statement
