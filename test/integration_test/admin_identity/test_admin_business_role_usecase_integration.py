"""
管理员业务角色用例集成测试模块。
"""

from __future__ import annotations

from http import HTTPStatus
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from src.api.testing.test_app_factory import TestAppFactory
from src.application.admin.identity.shared.admin_identity_command import (
    AdminUserCreateCommand,
)
from src.application.ports.admin_identity_port import (
    AdminRoleListQuery,
    AdminUserListQuery,
    BusinessAdminRoleKey,
)
from src.domain.auth.auth_role_key import AuthRoleKey
from src.infrastructure.persistence.orm_model.auth_role_orm_model import AuthRoleOrmModel
from src.infrastructure.persistence.orm_model.auth_user_orm_model import AuthUserOrmModel
from src.infrastructure.persistence.repository_impl.admin_identity_repository_impl import (
    AdminIdentityRepositoryImpl,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.usefixtures("integration_database"),
]

BUSINESS_ROLE_PAGE_SIZE = 50
BUSINESS_ROLE_OFFSET = 0
BUSINESS_ROLE_PASSWORD = "business-role-unit-password"
BUSINESS_ROLE_USERNAME = "business_role_unit_user"
BUSINESS_ROLE_SUBJECT_ID = "business-role-unit-user"
BUSINESS_ROLE_SQL_PAGE_SIZE = 10
BUSINESS_ROLE_SQL_OFFSET = 5
BUSINESS_ROLE_SQL_KEYWORD = "customer"
BUSINESS_ROLE_SQL_LIMIT_TEXT = "LIMIT 10"
BUSINESS_ROLE_SQL_OFFSET_TEXT = "OFFSET 5"
BUSINESS_ROLE_SQL_WHERE_TEXT = "WHERE"
BUSINESS_ROLE_SQL_ORDER_TEXT = "ORDER BY"
BUSINESS_ROLE_SQL_COUNT_TEXT = "count("
BUSINESS_ROLE_SQL_ROLE_FILTER_TEXT = "auth_role.role_key IN"
BUSINESS_ROLE_SQL_USER_FILTER_TEXT = "auth_role.role_key = 'customer_service'"
BUSINESS_ROLE_SQL_ACTIVE_FILTER_TEXT = "auth_user.is_active = true"
BUSINESS_ROLE_SQL_KEYWORD_FILTER_TEXT = "ILIKE"
BUSINESS_ROLE_SQL_ROLE_ORDER_TEXT = "ORDER BY auth_role.role_key ASC"
BUSINESS_ROLE_SQL_USER_ORDER_TEXT = "ORDER BY auth_user.username ASC, auth_user.subject_id ASC"


class TestAdminBusinessRoleUsecaseIntegration:
    """
    管理员业务角色用例测试集合。
    """

    def test_list_admin_roles_should_return_only_business_roles(self) -> None:
        """
        验证角色列表只返回预定义业务角色。
        """

        app = TestAppFactory().create()
        with TestClient(app):
            page = app.state.container.resource_mount.list_admin_roles(
                AdminRoleListQuery(
                    keyword=None,
                    page_size=BUSINESS_ROLE_PAGE_SIZE,
                    offset=BUSINESS_ROLE_OFFSET,
                    business_only=True,
                )
            )

        role_keys = {role.role_key for role in page.roles}

        assert role_keys == {
            BusinessAdminRoleKey.CUSTOMER_SERVICE.value,
            BusinessAdminRoleKey.BUSINESS_OPERATOR.value,
        }
        assert page.page_size == BUSINESS_ROLE_PAGE_SIZE
        assert page.offset == BUSINESS_ROLE_OFFSET

    def test_user_create_when_technical_role_assigned_should_fail(self) -> None:
        """
        验证用户创建拒绝技术角色。
        """

        app = TestAppFactory().create()
        with TestClient(app):
            with pytest.raises(Exception) as fault:
                app.state.container.resource_mount.create_admin_user(
                    AdminUserCreateCommand(
                        username=BUSINESS_ROLE_USERNAME,
                        password_plain=BUSINESS_ROLE_PASSWORD,
                        role_keys=[AuthRoleKey.ADMIN.value],
                        subject_id=BUSINESS_ROLE_SUBJECT_ID,
                    )
                )

        assert getattr(fault.value, "status_code", None) == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_list_admin_roles_should_filter_keyword_before_pagination(self) -> None:
        """
        验证业务角色关键字过滤先于分页生效。
        """

        app = TestAppFactory().create()
        with TestClient(app):
            page = app.state.container.resource_mount.list_admin_roles(
                AdminRoleListQuery(
                    keyword=BusinessAdminRoleKey.CUSTOMER_SERVICE.value,
                    page_size=BUSINESS_ROLE_PAGE_SIZE,
                    offset=BUSINESS_ROLE_OFFSET,
                    business_only=True,
                )
            )

        assert [role.role_key for role in page.roles] == [
            BusinessAdminRoleKey.CUSTOMER_SERVICE.value
        ]
        assert page.total == 1

    def test_role_and_user_list_sql_should_push_filter_sort_and_page_down(self) -> None:
        """
        验证业务角色与用户列表 SQL 包含过滤、排序和分页下推。
        """

        repository = AdminIdentityRepositoryImpl(Mock(spec=Session))
        role_statement = (
            repository._build_business_role_statement(
                AdminRoleListQuery(
                    keyword=BUSINESS_ROLE_SQL_KEYWORD,
                    page_size=BUSINESS_ROLE_SQL_PAGE_SIZE,
                    offset=BUSINESS_ROLE_SQL_OFFSET,
                    business_only=True,
                )
            )
            .order_by(AuthRoleOrmModel.role_key.asc())
            .offset(BUSINESS_ROLE_SQL_OFFSET)
            .limit(BUSINESS_ROLE_SQL_PAGE_SIZE)
        )
        user_statement = (
            repository._build_user_list_statement(
                AdminUserListQuery(
                    keyword=BUSINESS_ROLE_SQL_KEYWORD,
                    role_key=BusinessAdminRoleKey.CUSTOMER_SERVICE.value,
                    is_active=True,
                    page_size=BUSINESS_ROLE_SQL_PAGE_SIZE,
                    offset=BUSINESS_ROLE_SQL_OFFSET,
                )
            )
            .order_by(
                AuthUserOrmModel.username.asc(),
                AuthUserOrmModel.subject_id.asc(),
            )
            .offset(BUSINESS_ROLE_SQL_OFFSET)
            .limit(BUSINESS_ROLE_SQL_PAGE_SIZE)
        )
        role_count_statement = repository._build_role_count_statement(
            repository._build_business_role_statement(
                AdminRoleListQuery(
                    keyword=BUSINESS_ROLE_SQL_KEYWORD,
                    page_size=BUSINESS_ROLE_SQL_PAGE_SIZE,
                    offset=BUSINESS_ROLE_SQL_OFFSET,
                    business_only=True,
                )
            )
        )
        user_count_statement = repository._build_user_count_statement(
            repository._build_user_list_statement(
                AdminUserListQuery(
                    keyword=BUSINESS_ROLE_SQL_KEYWORD,
                    role_key=BusinessAdminRoleKey.CUSTOMER_SERVICE.value,
                    is_active=True,
                    page_size=BUSINESS_ROLE_SQL_PAGE_SIZE,
                    offset=BUSINESS_ROLE_SQL_OFFSET,
                )
            )
        )

        role_sql = self._compile_sql(role_statement)
        user_sql = self._compile_sql(user_statement)
        role_count_sql = self._compile_sql(role_count_statement)
        user_count_sql = self._compile_sql(user_count_statement)

        assert BUSINESS_ROLE_SQL_ROLE_FILTER_TEXT in role_sql
        assert BUSINESS_ROLE_SQL_KEYWORD_FILTER_TEXT in role_sql
        assert BUSINESS_ROLE_SQL_LIMIT_TEXT in role_sql
        assert BUSINESS_ROLE_SQL_OFFSET_TEXT in role_sql
        assert BUSINESS_ROLE_SQL_ROLE_ORDER_TEXT in role_sql
        assert role_sql.index(BUSINESS_ROLE_SQL_WHERE_TEXT) < role_sql.index(
            BUSINESS_ROLE_SQL_ORDER_TEXT
        )
        assert role_sql.index(BUSINESS_ROLE_SQL_ORDER_TEXT) < role_sql.index(
            BUSINESS_ROLE_SQL_LIMIT_TEXT
        )
        assert BUSINESS_ROLE_SQL_USER_FILTER_TEXT in user_sql
        assert BUSINESS_ROLE_SQL_ACTIVE_FILTER_TEXT in user_sql
        assert BUSINESS_ROLE_SQL_KEYWORD_FILTER_TEXT in user_sql
        assert BUSINESS_ROLE_SQL_LIMIT_TEXT in user_sql
        assert BUSINESS_ROLE_SQL_OFFSET_TEXT in user_sql
        assert BUSINESS_ROLE_SQL_USER_ORDER_TEXT in user_sql
        assert BUSINESS_ROLE_SQL_COUNT_TEXT in role_count_sql.lower()
        assert BUSINESS_ROLE_SQL_ROLE_FILTER_TEXT in role_count_sql
        assert BUSINESS_ROLE_SQL_KEYWORD_FILTER_TEXT in role_count_sql
        assert BUSINESS_ROLE_SQL_COUNT_TEXT in user_count_sql.lower()
        assert BUSINESS_ROLE_SQL_USER_FILTER_TEXT in user_count_sql
        assert BUSINESS_ROLE_SQL_ACTIVE_FILTER_TEXT in user_count_sql
        assert BUSINESS_ROLE_SQL_KEYWORD_FILTER_TEXT in user_count_sql

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
