"""
管理员身份 RBAC 集成测试模块。
"""

from __future__ import annotations

from http import HTTPStatus
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.endpoint_admin_identity.contract_admin_identity_common import (
    ADMIN_IDENTITY_GRANT_CONFIRMATION_PHRASE,
    ADMIN_IDENTITY_SCHEMA_VERSION,
    AdminIdentityHeader,
    AdminIdentityOperationName,
    AdminIdentityPayloadKind,
)
from src.api.endpoint_admin_identity.contract_admin_identity_envelope import (
    AdminIdentityEnvelope,
)
from src.api.endpoint_admin_identity.contract_admin_scope import AdminScopeUpdateRequest
from src.api.endpoint_admin_identity.contract_admin_user import (
    AdminUserDisableRequest,
    AdminUserRoleReplaceRequest,
)
from src.api.endpoint_admin_identity.route_admin_identity_common import (
    ADMIN_SCOPE_DETAIL_PATH,
    ADMIN_SCOPES_PATH,
    ADMIN_USER_DISABLE_PATH,
    ADMIN_USER_PASSWORD_PATH,
    ADMIN_USER_ROLES_PATH,
    ADMIN_USERS_PATH,
)
from src.api.testing.test_app_factory import TestAppFactory
from src.application.ports.admin_identity_port import BusinessAdminRoleKey
from src.domain.auth.auth_scope_code import AuthScopeCode
from src.infrastructure.persistence.orm_model.auth_user_orm_model import AuthUserOrmModel

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.usefixtures("integration_database"),
]


AUTH_TOKEN_PATH = "/auth/token"
AUTH_REFRESH_PATH = "/auth/refresh"
AUTHORIZATION_HEADER = "Authorization"
BEARER_PREFIX = "Bearer"
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin"
DATA_FIELD = "data"
ACCESS_TOKEN_FIELD = "access_token"
REFRESH_TOKEN_FIELD = "refresh_token"
INTEGRATION_USER_PASSWORD = "identity-integration-password"
INTEGRATION_USER_NEW_PASSWORD = "identity-integration-new-password"
INTEGRATION_EMPTY_ROLE_KEYS: tuple[str, ...] = ()
CUSTOMER_SERVICE_ROLE = BusinessAdminRoleKey.CUSTOMER_SERVICE.value
PROTECTED_SCOPE_CODE = AuthScopeCode.SECURITY_MANAGE.value


class TestAdminIdentityRbacIntegration:
    """
    管理员身份 RBAC 集成测试集合。
    """

    def test_admin_identity_should_create_user_login_and_revoke_session(self) -> None:
        """
        验证创建用户、绑定业务角色、登录、权限隔离和会话撤销。
        """

        username = self._build_username()
        subject_id = self._build_subject_id()
        app = TestAppFactory().create()
        with TestClient(app) as client:
            admin_token = self._issue_token_bundle(
                client=client,
                username=ADMIN_USERNAME,
                password=ADMIN_PASSWORD,
            )[ACCESS_TOKEN_FIELD]
            admin_header = self._build_auth_header(admin_token)
            try:
                create_response = client.post(
                    ADMIN_USERS_PATH,
                    headers=admin_header,
                    json=self._build_user_create_body(
                        username=username,
                        subject_id=subject_id,
                    ),
                )
                user_tokens = self._issue_token_bundle(
                    client=client,
                    username=username,
                    password=INTEGRATION_USER_PASSWORD,
                )
                permission_response = client.get(
                    ADMIN_USERS_PATH,
                    headers=self._build_auth_header(user_tokens[ACCESS_TOKEN_FIELD]),
                )
                reset_response = client.post(
                    ADMIN_USER_PASSWORD_PATH.format(subject_id=subject_id),
                    headers=admin_header,
                    json=self._build_password_reset_body(),
                )
                refresh_response = client.post(
                    AUTH_REFRESH_PATH,
                    json={REFRESH_TOKEN_FIELD: user_tokens[REFRESH_TOKEN_FIELD]},
                )
            finally:
                self._cleanup(app=app, subject_ids=[subject_id])

        assert create_response.status_code == HTTPStatus.OK
        assert permission_response.status_code == HTTPStatus.FORBIDDEN
        assert reset_response.status_code == HTTPStatus.OK
        assert refresh_response.status_code == HTTPStatus.UNAUTHORIZED

    def test_user_role_replace_should_revoke_refresh_token_session(self) -> None:
        """
        验证用户角色替换后撤销既有刷新令牌会话。
        """

        username = self._build_username()
        subject_id = self._build_subject_id()
        app = TestAppFactory().create()
        with TestClient(app) as client:
            admin_token = self._issue_token_bundle(
                client=client,
                username=ADMIN_USERNAME,
                password=ADMIN_PASSWORD,
            )[ACCESS_TOKEN_FIELD]
            admin_header = self._build_auth_header(admin_token)
            try:
                create_response = client.post(
                    ADMIN_USERS_PATH,
                    headers=admin_header,
                    json=self._build_user_create_body(
                        username=username,
                        subject_id=subject_id,
                    ),
                )
                user_tokens = self._issue_token_bundle(
                    client=client,
                    username=username,
                    password=INTEGRATION_USER_PASSWORD,
                )
                replace_response = client.post(
                    ADMIN_USER_ROLES_PATH.format(subject_id=subject_id),
                    headers=admin_header,
                    json=self._build_user_role_replace_body(
                        role_keys=INTEGRATION_EMPTY_ROLE_KEYS,
                    ),
                )
                refresh_response = client.post(
                    AUTH_REFRESH_PATH,
                    json={REFRESH_TOKEN_FIELD: user_tokens[REFRESH_TOKEN_FIELD]},
                )
            finally:
                self._cleanup(app=app, subject_ids=[subject_id])

        assert create_response.status_code == HTTPStatus.OK
        assert replace_response.status_code == HTTPStatus.OK
        assert refresh_response.status_code == HTTPStatus.UNAUTHORIZED

    def test_user_delete_should_revoke_refresh_token_session(self) -> None:
        """
        验证用户停用后撤销既有刷新令牌会话。
        """

        username = self._build_username()
        subject_id = self._build_subject_id()
        app = TestAppFactory().create()
        with TestClient(app) as client:
            admin_token = self._issue_token_bundle(
                client=client,
                username=ADMIN_USERNAME,
                password=ADMIN_PASSWORD,
            )[ACCESS_TOKEN_FIELD]
            admin_header = self._build_auth_header(admin_token)
            try:
                create_response = client.post(
                    ADMIN_USERS_PATH,
                    headers=admin_header,
                    json=self._build_user_create_body(
                        username=username,
                        subject_id=subject_id,
                    ),
                )
                user_tokens = self._issue_token_bundle(
                    client=client,
                    username=username,
                    password=INTEGRATION_USER_PASSWORD,
                )
                disable_response = client.post(
                    ADMIN_USER_DISABLE_PATH.format(subject_id=subject_id),
                    headers=admin_header,
                    json=self._build_user_disable_body(),
                )
                refresh_response = client.post(
                    AUTH_REFRESH_PATH,
                    json={REFRESH_TOKEN_FIELD: user_tokens[REFRESH_TOKEN_FIELD]},
                )
            finally:
                self._cleanup(app=app, subject_ids=[subject_id])

        assert create_response.status_code == HTTPStatus.OK
        assert disable_response.status_code == HTTPStatus.OK
        assert refresh_response.status_code == HTTPStatus.UNAUTHORIZED

    def test_admin_should_keep_identity_access_after_protected_scope_disable_failed(
        self,
    ) -> None:
        """
        验证受保护 scope 禁用失败后管理员仍可访问身份管理接口。
        """

        app = TestAppFactory().create()
        with TestClient(app) as client:
            admin_token = self._issue_token_bundle(
                client=client,
                username=ADMIN_USERNAME,
                password=ADMIN_PASSWORD,
            )[ACCESS_TOKEN_FIELD]
            admin_header = self._build_auth_header(admin_token)
            disable_response = client.patch(
                ADMIN_SCOPE_DETAIL_PATH.format(scope_code=PROTECTED_SCOPE_CODE),
                headers=admin_header,
                json=self._build_scope_update_body(enabled=False),
            )
            users_response = client.get(ADMIN_USERS_PATH, headers=admin_header)
            scopes_response = client.get(ADMIN_SCOPES_PATH, headers=admin_header)

        assert disable_response.status_code == HTTPStatus.CONFLICT
        assert users_response.status_code == HTTPStatus.OK
        assert scopes_response.status_code == HTTPStatus.OK

    def _build_username(self) -> str:
        """
        构建集成测试用户名。
        """

        return f"identity_integration_{uuid4().hex}"

    def _build_subject_id(self) -> str:
        """
        构建集成测试主体标识。
        """

        return f"identity-integration-{uuid4()}"

    def _build_user_create_body(
        self,
        *,
        username: str,
        subject_id: str,
    ) -> dict[str, object]:
        """
        构建用户创建请求体。
        """

        return {
            "header": {
                "kind": AdminIdentityPayloadKind.USER_CREATE.value,
                "schema_version": ADMIN_IDENTITY_SCHEMA_VERSION,
                "operation_name": AdminIdentityOperationName.USER_CREATE.value,
            },
            "detail": {
                "kind": AdminIdentityPayloadKind.USER_CREATE.value,
                "schema_version": ADMIN_IDENTITY_SCHEMA_VERSION,
                "username": username,
                "password": INTEGRATION_USER_PASSWORD,
                "role_keys": [CUSTOMER_SERVICE_ROLE],
                "subject_id": subject_id,
            },
        }

    def _build_password_reset_body(self) -> dict[str, object]:
        """
        构建密码重置请求体。
        """

        return {
            "header": {
                "kind": AdminIdentityPayloadKind.USER_PASSWORD_RESET.value,
                "schema_version": ADMIN_IDENTITY_SCHEMA_VERSION,
                "operation_name": AdminIdentityOperationName.USER_PASSWORD_RESET.value,
            },
            "detail": {
                "kind": AdminIdentityPayloadKind.USER_PASSWORD_RESET.value,
                "schema_version": ADMIN_IDENTITY_SCHEMA_VERSION,
                "password": INTEGRATION_USER_NEW_PASSWORD,
            },
        }

    def _build_user_role_replace_body(
        self,
        *,
        role_keys: list[str] | tuple[str, ...],
    ) -> dict[str, object]:
        """
        构建用户角色替换请求体。
        """

        return AdminIdentityEnvelope(
            header=AdminIdentityHeader(
                kind=AdminIdentityPayloadKind.USER_ROLE_REPLACE,
                schema_version=ADMIN_IDENTITY_SCHEMA_VERSION,
                operation_name=AdminIdentityOperationName.USER_ROLE_REPLACE,
            ),
            detail=AdminUserRoleReplaceRequest(
                role_keys=list(role_keys),
                confirmation=ADMIN_IDENTITY_GRANT_CONFIRMATION_PHRASE,
            ),
        ).model_dump(mode="json")

    def _build_user_disable_body(self) -> dict[str, object]:
        """
        构建用户停用请求体。
        """

        return AdminIdentityEnvelope(
            header=AdminIdentityHeader(
                kind=AdminIdentityPayloadKind.USER_DISABLE,
                schema_version=ADMIN_IDENTITY_SCHEMA_VERSION,
                operation_name=AdminIdentityOperationName.USER_DISABLE,
            ),
            detail=AdminUserDisableRequest(reason="集成测试停用"),
        ).model_dump(mode="json")

    def _build_scope_update_body(self, *, enabled: bool) -> dict[str, object]:
        """
        构建 scope 更新请求体。
        """

        return AdminIdentityEnvelope(
            header=AdminIdentityHeader(
                kind=AdminIdentityPayloadKind.SCOPE_UPDATE,
                schema_version=ADMIN_IDENTITY_SCHEMA_VERSION,
                operation_name=AdminIdentityOperationName.SCOPE_UPDATE,
            ),
            detail=AdminScopeUpdateRequest(enabled=enabled),
        ).model_dump(mode="json")

    def _issue_token_bundle(
        self,
        *,
        client: TestClient,
        username: str,
        password: str,
    ) -> dict[str, str]:
        """
        签发令牌对。
        """

        response = client.post(
            AUTH_TOKEN_PATH,
            json={"username": username, "password": password},
        )
        data = response.json()[DATA_FIELD]
        return {
            ACCESS_TOKEN_FIELD: str(data[ACCESS_TOKEN_FIELD]),
            REFRESH_TOKEN_FIELD: str(data[REFRESH_TOKEN_FIELD]),
        }

    def _build_auth_header(self, access_token: str) -> dict[str, str]:
        """
        构建认证请求头。
        """

        return {AUTHORIZATION_HEADER: f"{BEARER_PREFIX} {access_token}"}

    def _cleanup(self, *, app: FastAPI, subject_ids: list[str]) -> None:
        """
        清理测试用户。
        """

        resource_mount = app.state.container.resource_mount
        unit_of_work = resource_mount.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            users = (
                session.query(AuthUserOrmModel)
                .filter(AuthUserOrmModel.subject_id.in_(subject_ids))
                .all()
            )
            for user in users:
                session.delete(user)
            unit_of_work.commit()
        finally:
            unit_of_work.dispose()
