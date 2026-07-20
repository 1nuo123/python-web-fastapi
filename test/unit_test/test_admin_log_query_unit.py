"""
管理员日志查询用例单元测试模块。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from sqlalchemy import Select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from src.api.endpoint_admin_log.contract_admin_log import AdminLogRecordPayload
from src.application.admin.list_admin_log_records_usecase import (
    ListAdminLogRecordsUsecase,
)
from src.application.admin.list_admin_security_events_usecase import (
    ListAdminSecurityEventsUsecase,
)
from src.application.ports.admin_log_query_port import (
    AdminLogRecordFilter,
    AdminLogRecordSnapshot,
    AdminSecurityEventFilter,
    AdminUnparsedLogDetail,
)
from src.core.logging_contract.log_event_contract import LogEventKind, LogLevel
from src.core.security_contract.security_event_contract import (
    SecurityEventDecision,
    SecurityEventSeverity,
    SecurityEventType,
)
from src.infrastructure.persistence.repository_impl.log_record_repository_impl import (
    LOG_RECORD_QUERY_LIMIT_MAXIMUM,
    LogRecordRepositoryImpl,
)

TEST_EVENT_ID = "event-admin-log-unit-1"
TEST_REQUEST_ID = "request-admin-log-unit-1"
TEST_TRACE_ID = "trace-admin-log-unit-1"
TEST_SUBJECT_ID = "subject-admin-log-unit-1"
TEST_SOURCE_MODULE = "test_module"
TEST_SOURCE_COMPONENT = "test_component"
TEST_MESSAGE = "测试日志"
TEST_OCCURRED_EPOCH = 1700000000
TEST_LIMIT = 50
TEST_LIMIT_ABOVE_MAXIMUM = LOG_RECORD_QUERY_LIMIT_MAXIMUM + 1
UNPARSED_SUMMARY = "历史日志详情无法按当前强类型契约解析。"
EXPECTED_LOG_LEVEL_SQL = "app_log_record.level = 'ERROR'"
EXPECTED_EVENT_KIND_SQL = "app_log_record.event_kind = 'exception'"
EXPECTED_REQUEST_ID_SQL = "app_log_record.request_id = 'request-admin-log-unit-1'"
EXPECTED_TRACE_ID_SQL = "app_log_record.trace_id = 'trace-admin-log-unit-1'"
EXPECTED_OCCURRED_FROM_SQL = "app_log_record.occurred_at >= "
EXPECTED_OCCURRED_TO_SQL = "app_log_record.occurred_at <= "
EXPECTED_LIMIT_SQL = "LIMIT 200"
EXPECTED_SECURITY_EVENT_TYPE_SQL = "authz.denied"
EXPECTED_SECURITY_EVENT_SEVERITY_SQL = "warning"
EXPECTED_SECURITY_EVENT_DECISION_SQL = "deny"


class EmptyLogRecordScalarResult:
    """
    空日志记录标量结果测试替身。
    """

    def all(self) -> list[object]:
        """
        返回空日志记录列表。
        """

        return []


class EmptyLogRecordExecuteResult:
    """
    空日志记录执行结果测试替身。
    """

    def scalars(self) -> EmptyLogRecordScalarResult:
        """
        返回空标量结果。
        """

        return EmptyLogRecordScalarResult()


class LogRecordStatementSession:
    """
    记录日志查询语句的会话测试替身。
    """

    def __init__(self) -> None:
        """
        初始化会话测试替身。
        """

        self.statement: object | None = None

    def execute(self, statement: object) -> EmptyLogRecordExecuteResult:
        """
        记录执行语句并返回空结果。
        """

        self.statement = statement
        return EmptyLogRecordExecuteResult()


class AdminLogQueryPortStub:
    """
    管理员日志查询端口测试替身。
    """

    def __init__(self) -> None:
        """
        初始化测试替身。
        """

        self.log_filter: AdminLogRecordFilter | None = None
        self.security_filter: AdminSecurityEventFilter | None = None

    def list_admin_log_records(
        self,
        query_filter: AdminLogRecordFilter,
    ) -> list[AdminLogRecordSnapshot]:
        """
        查询应用日志记录。
        """

        self.log_filter = query_filter
        return [self._build_unparsed_snapshot()]

    def list_admin_security_events(
        self,
        query_filter: AdminSecurityEventFilter,
    ) -> list[AdminLogRecordSnapshot]:
        """
        查询安全事件记录。
        """

        self.security_filter = query_filter
        return []

    def _build_unparsed_snapshot(self) -> AdminLogRecordSnapshot:
        """
        构建不可解析日志快照。
        """

        return AdminLogRecordSnapshot(
            event_id=TEST_EVENT_ID,
            event_kind=LogEventKind.EXCEPTION,
            schema_version="0.1",
            level=LogLevel.ERROR,
            message=TEST_MESSAGE,
            occurred_at=datetime.fromtimestamp(TEST_OCCURRED_EPOCH, UTC),
            request_id=TEST_REQUEST_ID,
            trace_id=TEST_TRACE_ID,
            authenticated_subject_id=TEST_SUBJECT_ID,
            source_module=TEST_SOURCE_MODULE,
            source_component=TEST_SOURCE_COMPONENT,
            detail=AdminUnparsedLogDetail(summary=UNPARSED_SUMMARY),
            security_event=None,
        )


class TestAdminLogQueryUnit:
    """
    管理员日志查询用例单元测试集合。
    """

    def test_log_records_usecase_should_pass_filter(self) -> None:
        """
        验证日志记录查询用例会传递过滤条件。
        """

        port = AdminLogQueryPortStub()
        records = ListAdminLogRecordsUsecase(admin_log_query_port=port).execute(
            AdminLogRecordFilter(
                level=LogLevel.ERROR,
                event_kind=LogEventKind.EXCEPTION,
                request_id=TEST_REQUEST_ID,
                trace_id=TEST_TRACE_ID,
                occurred_from=None,
                occurred_to=None,
                limit=TEST_LIMIT,
            )
        )

        assert len(records) == 1
        assert port.log_filter is not None
        assert port.log_filter.level == LogLevel.ERROR
        assert port.log_filter.request_id == TEST_REQUEST_ID

    def test_security_events_usecase_should_pass_filter(self) -> None:
        """
        验证安全事件查询用例会传递过滤条件。
        """

        port = AdminLogQueryPortStub()
        records = ListAdminSecurityEventsUsecase(admin_log_query_port=port).execute(
            AdminSecurityEventFilter(
                event_type=None,
                severity=None,
                decision=None,
                occurred_from=None,
                occurred_to=None,
                limit=TEST_LIMIT,
            )
        )

        assert records == []
        assert port.security_filter is not None
        assert port.security_filter.limit == TEST_LIMIT

    def test_log_record_repository_should_apply_all_supported_filters(self) -> None:
        """
        验证日志仓储会应用全部受控过滤条件。
        """

        fake_session = LogRecordStatementSession()
        repository = LogRecordRepositoryImpl(cast(Session, fake_session))
        records = repository.list_records(
            limit=TEST_LIMIT_ABOVE_MAXIMUM,
            level=LogLevel.ERROR,
            event_kind=LogEventKind.EXCEPTION,
            request_id=TEST_REQUEST_ID,
            trace_id=TEST_TRACE_ID,
            occurred_from=datetime.fromtimestamp(TEST_OCCURRED_EPOCH, UTC),
            occurred_to=datetime.fromtimestamp(TEST_OCCURRED_EPOCH + TEST_LIMIT, UTC),
            security_event_type=SecurityEventType.AUTHZ_DENIED,
            security_event_severity=SecurityEventSeverity.WARNING,
            security_event_decision=SecurityEventDecision.DENY,
        )
        compiled_sql = self._compile_statement(fake_session.statement)

        assert records == []
        assert EXPECTED_LOG_LEVEL_SQL in compiled_sql
        assert EXPECTED_EVENT_KIND_SQL in compiled_sql
        assert EXPECTED_REQUEST_ID_SQL in compiled_sql
        assert EXPECTED_TRACE_ID_SQL in compiled_sql
        assert EXPECTED_OCCURRED_FROM_SQL in compiled_sql
        assert EXPECTED_OCCURRED_TO_SQL in compiled_sql
        assert EXPECTED_SECURITY_EVENT_TYPE_SQL in compiled_sql
        assert EXPECTED_SECURITY_EVENT_SEVERITY_SQL in compiled_sql
        assert EXPECTED_SECURITY_EVENT_DECISION_SQL in compiled_sql
        assert EXPECTED_LIMIT_SQL in compiled_sql

    def test_unparsed_snapshot_should_map_to_summary_payload(self) -> None:
        """
        验证不可解析历史详情会降级为摘要载荷。
        """

        payload = AdminLogRecordPayload.from_snapshot(
            AdminLogQueryPortStub()._build_unparsed_snapshot()
        )

        assert payload.detail.summary == UNPARSED_SUMMARY

    def _compile_statement(self, statement: object | None) -> str:
        """
        编译 SQLAlchemy 查询语句。
        """

        if statement is None:
            raise AssertionError("日志仓储未执行查询语句。")
        return str(
            cast(Select[tuple[object]], statement).compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )
