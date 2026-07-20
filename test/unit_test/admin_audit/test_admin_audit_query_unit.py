"""
业务审计查询单元测试模块。
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import Mock

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from src.api.endpoint_admin_audit.contract_admin_audit import AdminAuditQueryPayload
from src.application.admin.audit.list_admin_audit_events_usecase import (
    ListAdminAuditEventsUsecase,
)
from src.application.ports.admin_audit_query_port import (
    AdminAuditAction,
    AdminAuditEventPage,
    AdminAuditEventSnapshot,
    AdminAuditQuery,
    AdminAuditResult,
)
from src.infrastructure.persistence.orm_model.app_log_record_orm_model import (
    AppLogRecordOrmModel,
)
from src.infrastructure.persistence.repository_impl.log_record_repository_impl import (
    LogRecordRepositoryImpl,
)
from src.infrastructure.resource_mount.shared_resource_constants import (
    ADMIN_AUDIT_OPERATION_BY_ACTION,
)

AUDIT_QUERY_EVENT_ID = "audit-query-unit-event"
AUDIT_QUERY_ACTOR_SUBJECT_ID = "audit-query-actor"
AUDIT_QUERY_TARGET_KIND = "user"
AUDIT_QUERY_TARGET_ID = "audit-query-target"
AUDIT_QUERY_SUMMARY = "业务审计查询单元测试。"
AUDIT_QUERY_OCCURRED_AT = datetime(2026, 5, 28, 10, 55, tzinfo=UTC)
AUDIT_QUERY_PAGE_SIZE = 25
AUDIT_QUERY_OFFSET = 5
AUDIT_QUERY_INVALID_PAGE_SIZE = 0
AUDIT_QUERY_EMPTY_TARGET_KIND = ""
AUDIT_SQL_OPERATION_NAME = "user_disable"
AUDIT_SQL_LIMIT_TEXT = "LIMIT 25"
AUDIT_SQL_OFFSET_TEXT = "OFFSET 5"
AUDIT_SQL_WHERE_TEXT = "WHERE"
AUDIT_SQL_ORDER_BY_TEXT = "ORDER BY"
AUDIT_SQL_COUNT_TEXT = "count("
AUDIT_SQL_ACTOR_FIELD_TEXT = "actor_subject_id"
AUDIT_SQL_TARGET_KIND_FIELD_TEXT = "target_kind"
AUDIT_SQL_TARGET_ID_FIELD_TEXT = "target_id"
AUDIT_SQL_OPERATION_FIELD_TEXT = "operation_name"
AUDIT_SQL_OCCURRED_FROM_TEXT = "app_log_record.occurred_at >="
AUDIT_SQL_OCCURRED_TO_TEXT = "app_log_record.occurred_at <="


class AdminAuditQueryPortStub:
    """
    业务审计查询端口测试桩。
    """

    def __init__(self, page: AdminAuditEventPage) -> None:
        """
        初始化测试桩。
        """

        self.page = page
        self.received_query: AdminAuditQuery | None = None

    def list_admin_audit_events(
        self,
        query: AdminAuditQuery,
    ) -> AdminAuditEventPage:
        """
        记录查询并返回分页。
        """

        self.received_query = query
        return self.page


class TestAdminAuditQueryUnit:
    """
    业务审计查询单元测试集合。
    """

    def test_usecase_should_pass_query_to_port(self) -> None:
        """
        验证用例透传查询对象到端口。
        """

        page = self._build_page()
        port = AdminAuditQueryPortStub(page)
        query = self._build_query(AdminAuditAction.USER_DISABLED)

        result = ListAdminAuditEventsUsecase(admin_audit_query_port=port).execute(query)

        assert result is page
        assert port.received_query == query

    def test_action_whitelist_should_contain_business_identity_actions(self) -> None:
        """
        验证业务审计动作白名单包含身份业务动作。
        """

        action_values = {action.value for action in AdminAuditAction}

        assert AdminAuditAction.USER_DISABLED.value in action_values
        assert AdminAuditAction.USER_ENABLED.value in action_values
        assert AdminAuditAction.PASSWORD_RESET.value in action_values
        assert AdminAuditAction.ROLE_ASSIGNED.value in action_values

    def test_query_should_keep_pagination_and_filter_fields(self) -> None:
        """
        验证查询对象保留过滤与分页字段。
        """

        query = self._build_query(AdminAuditAction.PASSWORD_RESET)

        assert query.actor_subject_id == AUDIT_QUERY_ACTOR_SUBJECT_ID
        assert query.target_kind == AUDIT_QUERY_TARGET_KIND
        assert query.target_id == AUDIT_QUERY_TARGET_ID
        assert query.page_size == AUDIT_QUERY_PAGE_SIZE
        assert query.offset == AUDIT_QUERY_OFFSET

    def test_query_payload_when_invalid_boundary_should_fail(self) -> None:
        """
        验证业务审计查询契约拒绝非法分页与过滤边界。
        """

        with pytest.raises(ValidationError):
            AdminAuditQueryPayload(page_size=AUDIT_QUERY_INVALID_PAGE_SIZE)
        with pytest.raises(ValidationError):
            AdminAuditQueryPayload(target_kind=AUDIT_QUERY_EMPTY_TARGET_KIND)

    def test_business_audit_whitelist_should_resolve_all_query_operations(self) -> None:
        """
        验证业务审计白名单覆盖无 action 查询使用的全部操作名。
        """

        operation_names = {
            operation_name
            for operation_names in ADMIN_AUDIT_OPERATION_BY_ACTION.values()
            for operation_name in operation_names
        }

        assert AUDIT_SQL_OPERATION_NAME in operation_names
        assert all(
            isinstance(action, AdminAuditAction) for action in ADMIN_AUDIT_OPERATION_BY_ACTION
        )

    def test_business_audit_sql_should_push_filter_sort_and_page_down(self) -> None:
        """
        验证业务审计仓储 SQL 包含过滤、排序、分页和统计下推。
        """

        repository = LogRecordRepositoryImpl(Mock(spec=Session))
        statement = repository._build_business_audit_statement(
            operation_names=[AUDIT_SQL_OPERATION_NAME],
            actor_subject_id=AUDIT_QUERY_ACTOR_SUBJECT_ID,
            target_kind=AUDIT_QUERY_TARGET_KIND,
            target_id=AUDIT_QUERY_TARGET_ID,
            occurred_from=AUDIT_QUERY_OCCURRED_AT,
            occurred_to=AUDIT_QUERY_OCCURRED_AT,
        )
        paged_statement = (
            statement.order_by(
                AppLogRecordOrmModel.occurred_at.desc(),
                AppLogRecordOrmModel.log_record_id.desc(),
            )
            .offset(AUDIT_QUERY_OFFSET)
            .limit(AUDIT_QUERY_PAGE_SIZE)
        )
        count_statement = repository._build_business_audit_count_statement(statement)

        paged_sql = self._compile_sql(paged_statement)
        count_sql = self._compile_sql(count_statement)

        assert AUDIT_SQL_ACTOR_FIELD_TEXT in paged_sql
        assert AUDIT_SQL_TARGET_KIND_FIELD_TEXT in paged_sql
        assert AUDIT_SQL_TARGET_ID_FIELD_TEXT in paged_sql
        assert AUDIT_SQL_OPERATION_FIELD_TEXT in paged_sql
        assert AUDIT_SQL_OCCURRED_FROM_TEXT in paged_sql
        assert AUDIT_SQL_OCCURRED_TO_TEXT in paged_sql
        assert AUDIT_SQL_LIMIT_TEXT in paged_sql
        assert AUDIT_SQL_OFFSET_TEXT in paged_sql
        assert paged_sql.index(AUDIT_SQL_WHERE_TEXT) < paged_sql.index(AUDIT_SQL_ORDER_BY_TEXT)
        assert paged_sql.index(AUDIT_SQL_ORDER_BY_TEXT) < paged_sql.index(AUDIT_SQL_LIMIT_TEXT)
        assert AUDIT_SQL_COUNT_TEXT in count_sql.lower()

    def _build_query(self, action: AdminAuditAction) -> AdminAuditQuery:
        """
        构建业务审计查询对象。
        """

        return AdminAuditQuery(
            actor_subject_id=AUDIT_QUERY_ACTOR_SUBJECT_ID,
            action=action,
            target_kind=AUDIT_QUERY_TARGET_KIND,
            target_id=AUDIT_QUERY_TARGET_ID,
            occurred_from=AUDIT_QUERY_OCCURRED_AT,
            occurred_to=AUDIT_QUERY_OCCURRED_AT,
            page_size=AUDIT_QUERY_PAGE_SIZE,
            offset=AUDIT_QUERY_OFFSET,
        )

    def _build_page(self) -> AdminAuditEventPage:
        """
        构建业务审计分页结果。
        """

        return AdminAuditEventPage(
            events=[
                AdminAuditEventSnapshot(
                    event_id=AUDIT_QUERY_EVENT_ID,
                    action=AdminAuditAction.USER_DISABLED,
                    actor_subject_id=AUDIT_QUERY_ACTOR_SUBJECT_ID,
                    target_kind=AUDIT_QUERY_TARGET_KIND,
                    target_id=AUDIT_QUERY_TARGET_ID,
                    result=AdminAuditResult.SUCCESS,
                    occurred_at=AUDIT_QUERY_OCCURRED_AT,
                    summary=AUDIT_QUERY_SUMMARY,
                )
            ],
            page_size=AUDIT_QUERY_PAGE_SIZE,
            offset=AUDIT_QUERY_OFFSET,
            total=1,
        )

    def _compile_sql(self, statement: object) -> str:
        """
        编译 SQL 语句。
        """

        return str(
            statement.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )
