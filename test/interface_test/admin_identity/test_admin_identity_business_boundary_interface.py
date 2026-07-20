"""
管理员身份业务边界接口测试模块。
"""

from __future__ import annotations

from http import HTTPStatus

from fastapi.testclient import TestClient

from src.api.endpoint_admin_audit.route_admin_audit import ADMIN_AUDIT_EVENTS_PATH
from src.api.endpoint_admin_identity.contract_admin_identity_common import (
    ADMIN_IDENTITY_GRANT_CONFIRMATION_PHRASE,
)
from src.api.endpoint_admin_identity.route_admin_identity_common import (
    ADMIN_BUSINESS_ROLES_PATH,
    ADMIN_ROLE_DETAIL_PATH,
    ADMIN_ROLE_SCOPES_PATH,
    ADMIN_ROLES_PATH,
    ADMIN_SCOPE_DETAIL_PATH,
    ADMIN_SCOPES_PATH,
    ADMIN_USER_DETAIL_PATH,
    ADMIN_USER_DISABLE_PATH,
    ADMIN_USER_ENABLE_PATH,
    ADMIN_USER_PASSWORD_PATH,
    ADMIN_USER_ROLES_PATH,
    ADMIN_USERS_PATH,
)
from src.api.testing.test_app_factory import TestAppFactory
from src.application.ports.admin_identity_port import BusinessAdminRoleKey
from src.domain.auth.auth_role_key import AuthRoleKey
from src.domain.auth.auth_scope_code import AuthScopeCode
from src.infrastructure.persistence.orm_model.auth_role_orm_model import AuthRoleOrmModel
from src.infrastructure.persistence.orm_model.auth_role_scope_orm_model import (
    AuthRoleScopeOrmModel,
)
from src.infrastructure.shared_resource_mount import SharedResourceMount

AUTH_TOKEN_PATH = "/auth/token"
OPENAPI_PATH = "/openapi.json"
AUTHORIZATION_HEADER = "Authorization"
BEARER_PREFIX = "Bearer"
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin"
DATA_FIELD = "data"
DETAIL_FIELD = "detail"
ROLES_FIELD = "roles"
ROLE_KEY_FIELD = "role_key"
ROLE_NAME_FIELD = "role_name"
SCOPE_CODES_FIELD = "scope_codes"
PAGE_SIZE_FIELD = "page_size"
OFFSET_FIELD = "offset"
INVALID_PAGE_SIZE = 0
CUSTOMER_SERVICE_ROLE = BusinessAdminRoleKey.CUSTOMER_SERVICE.value
BUSINESS_OPERATOR_ROLE = BusinessAdminRoleKey.BUSINESS_OPERATOR.value
DELETE_METHOD_FIELD = "delete"
CONFIRMATION_FIELD_NAME = "confirmation"
HEADER_FIELD_NAME = "header"
KIND_FIELD_NAME = "kind"
SCHEMA_VERSION_FIELD_NAME = "schema_version"
OPERATION_NAME_FIELD_NAME = "operation_name"
ADMIN_ROLE_CREATE_KIND = "admin_role_create"
ADMIN_ROLE_CREATE_OPERATION = "role_create"
ADMIN_IDENTITY_SCHEMA_VERSION = "1.0"
PROTECTED_ROLE_KEY = "business_boundary_protected_role"
PROTECTED_ROLE_NAME = "受保护角色"
ADMIN_ROLE_SCOPE_CODES = [scope.value for scope in AuthScopeCode]
LOW_PRIVILEGE_ROLE_SCOPE_CODES = [AuthScopeCode.AUTH_ROLE_MANAGE.value]


class TestAdminIdentityBusinessBoundaryInterface:
    """
    管理员身份业务边界接口测试集合。
    """

    def test_openapi_should_expose_complete_identity_surface(self) -> None:
        """
        验证默认 OpenAPI 暴露完整身份管理接口。
        """

        with TestClient(TestAppFactory().create()) as client:
            response = client.get(OPENAPI_PATH)

        paths = response.json()["paths"]

        assert response.status_code == HTTPStatus.OK
        assert ADMIN_USERS_PATH in paths
        assert ADMIN_ROLES_PATH in paths
        assert ADMIN_BUSINESS_ROLES_PATH in paths
        assert ADMIN_AUDIT_EVENTS_PATH in paths
        assert ADMIN_USER_DISABLE_PATH in paths
        assert ADMIN_USER_ENABLE_PATH in paths
        assert ADMIN_USER_PASSWORD_PATH in paths
        assert ADMIN_USER_ROLES_PATH in paths
        assert ADMIN_SCOPES_PATH in paths
        assert ADMIN_SCOPE_DETAIL_PATH in paths
        assert ADMIN_ROLE_DETAIL_PATH in paths
        assert ADMIN_ROLE_SCOPES_PATH in paths

    def test_legacy_user_disable_openapi_should_be_closed_by_default(
        self,
    ) -> None:
        """
        验证兼容旧 HTTP 方法的用户状态接口默认不暴露。
        """

        with TestClient(TestAppFactory().create()) as client:
            response = client.get(OPENAPI_PATH)

        methods = response.json()["paths"][ADMIN_USER_DETAIL_PATH]

        assert response.status_code == HTTPStatus.OK
        assert DELETE_METHOD_FIELD not in methods

    def test_role_list_should_be_business_readonly_and_paginated(self) -> None:
        """
        验证业务角色下拉为只读列表并带分页。
        """

        with TestClient(TestAppFactory().create()) as client:
            access_token = self._issue_admin_token(client)
            response = client.get(
                ADMIN_BUSINESS_ROLES_PATH,
                headers=self._build_auth_header(access_token),
                params={"page_size": 1, "offset": 0},
            )
            invalid_response = client.get(
                ADMIN_BUSINESS_ROLES_PATH,
                headers=self._build_auth_header(access_token),
                params={"page_size": INVALID_PAGE_SIZE},
            )

        detail = response.json()[DATA_FIELD][DETAIL_FIELD]
        roles = detail[ROLES_FIELD]

        assert response.status_code == HTTPStatus.OK
        assert detail[PAGE_SIZE_FIELD] == 1
        assert detail[OFFSET_FIELD] == 0
        assert roles[0][ROLE_KEY_FIELD] in {CUSTOMER_SERVICE_ROLE, BUSINESS_OPERATOR_ROLE}
        assert all(SCOPE_CODES_FIELD not in role for role in roles)
        assert invalid_response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_role_write_and_scope_routes_should_be_mounted(self) -> None:
        """
        验证角色写接口和 scope 接口默认已挂载。
        """

        with TestClient(TestAppFactory().create()) as client:
            access_token = self._issue_admin_token(client)
            auth_header = self._build_auth_header(access_token)
            role_write_response = client.post(ADMIN_ROLES_PATH, headers=auth_header)
            role_scope_response = client.put(
                ADMIN_ROLE_SCOPES_PATH.format(role_key=CUSTOMER_SERVICE_ROLE),
                headers=auth_header,
            )
            scope_response = client.get(ADMIN_SCOPES_PATH, headers=auth_header)

        assert role_write_response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        assert role_scope_response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        assert scope_response.status_code == HTTPStatus.OK

    def test_technical_role_assignment_should_return_unprocessable(self) -> None:
        """
        验证业务后台拒绝给用户分配技术角色。
        """

        with TestClient(TestAppFactory().create()) as client:
            access_token = self._issue_admin_token(client)
            response = client.post(
                ADMIN_USER_ROLES_PATH.format(subject_id="user-admin"),
                headers=self._build_auth_header(access_token),
                json={
                    "header": {
                        "kind": "admin_user_role_replace",
                        "schema_version": "1.0",
                        "operation_name": "user_role_replace",
                    },
                    "detail": {
                        "kind": "admin_user_role_replace",
                        "schema_version": "1.0",
                        "role_keys": [AuthRoleKey.ADMIN.value],
                        CONFIRMATION_FIELD_NAME: ADMIN_IDENTITY_GRANT_CONFIRMATION_PHRASE,
                    },
                },
            )

        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_role_create_with_protected_scope_should_require_grant_admin(
        self,
    ) -> None:
        """
        验证创建含受保护 scope 的角色必须具备高危授权能力。
        """

        app = TestAppFactory().create()
        with TestClient(app) as client:
            access_token = self._issue_admin_token(client)
            resource_mount = app.state.container.resource_mount
            try:
                self._replace_admin_role_scopes(
                    resource_mount=resource_mount,
                    scope_codes=LOW_PRIVILEGE_ROLE_SCOPE_CODES,
                )
                response = client.post(
                    ADMIN_ROLES_PATH,
                    headers=self._build_auth_header(access_token),
                    json={
                        HEADER_FIELD_NAME: {
                            KIND_FIELD_NAME: ADMIN_ROLE_CREATE_KIND,
                            SCHEMA_VERSION_FIELD_NAME: ADMIN_IDENTITY_SCHEMA_VERSION,
                            OPERATION_NAME_FIELD_NAME: ADMIN_ROLE_CREATE_OPERATION,
                        },
                        DETAIL_FIELD: {
                            KIND_FIELD_NAME: ADMIN_ROLE_CREATE_KIND,
                            SCHEMA_VERSION_FIELD_NAME: ADMIN_IDENTITY_SCHEMA_VERSION,
                            ROLE_KEY_FIELD: PROTECTED_ROLE_KEY,
                            ROLE_NAME_FIELD: PROTECTED_ROLE_NAME,
                            SCOPE_CODES_FIELD: [AuthScopeCode.AUTH_READ.value],
                            CONFIRMATION_FIELD_NAME: (ADMIN_IDENTITY_GRANT_CONFIRMATION_PHRASE),
                        },
                    },
                )
            finally:
                self._replace_admin_role_scopes(
                    resource_mount=resource_mount,
                    scope_codes=ADMIN_ROLE_SCOPE_CODES,
                )
                self._delete_role(
                    resource_mount=resource_mount,
                    role_key=PROTECTED_ROLE_KEY,
                )

        assert response.status_code == HTTPStatus.FORBIDDEN

    def _issue_admin_token(self, client: TestClient) -> str:
        """
        签发管理员访问令牌。
        """

        response = client.post(
            AUTH_TOKEN_PATH,
            json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
        )
        return str(response.json()[DATA_FIELD]["access_token"])

    def _build_auth_header(self, access_token: str) -> dict[str, str]:
        """
        构建认证请求头。
        """

        return {AUTHORIZATION_HEADER: f"{BEARER_PREFIX} {access_token}"}

    def _replace_admin_role_scopes(
        self,
        *,
        resource_mount: SharedResourceMount,
        scope_codes: list[str],
    ) -> None:
        """
        替换内置管理员角色 scope。
        """

        unit_of_work = resource_mount.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            admin_role = (
                session.query(AuthRoleOrmModel).filter_by(role_key=AuthRoleKey.ADMIN.value).one()
            )
            admin_role.role_scopes.clear()
            for scope_code in scope_codes:
                admin_role.role_scopes.append(AuthRoleScopeOrmModel(scope_code=scope_code))
            unit_of_work.commit()
        finally:
            unit_of_work.dispose()

    def _delete_role(
        self,
        *,
        resource_mount: SharedResourceMount,
        role_key: str,
    ) -> None:
        """
        删除测试角色。
        """

        unit_of_work = resource_mount.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            role = session.query(AuthRoleOrmModel).filter_by(role_key=role_key).one_or_none()
            if role is not None:
                session.delete(role)
            unit_of_work.commit()
        finally:
            unit_of_work.dispose()
