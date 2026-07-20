"""
管理员用户接口测试模块。
"""

from __future__ import annotations

from http import HTTPStatus
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import or_

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
from src.api.endpoint_admin_identity.contract_admin_user import (
    AdminUserDisableRequest,
    AdminUserEnableRequest,
    AdminUserRoleReplaceRequest,
    AdminUserUpdateRequest,
)
from src.api.endpoint_admin_identity.route_admin_identity_common import (
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
from src.infrastructure.persistence.orm_model.auth_user_orm_model import AuthUserOrmModel

AUTH_TOKEN_PATH = "/auth/token"
AUTHORIZATION_HEADER = "Authorization"
BEARER_PREFIX = "Bearer"
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin"
DATA_FIELD = "data"
DETAIL_FIELD = "detail"
SUBJECT_ID_FIELD = "subject_id"
USERNAME_FIELD = "username"
AUTH_ADMIN_ROLE = "admin"
AUTH_READ_SCOPE = "auth:read"
USER_INTERFACE_PASSWORD = "user-interface-password"
USER_INTERFACE_NEW_PASSWORD = "user-interface-new-password"
DEFAULT_ADMIN_SUBJECT_ID = "user-admin"
INVALID_LIMIT = 0
STATUS_FIELD = "status"
IS_ACTIVE_FIELD = "is_active"
CONFIRMATION_FIELD_NAME = "confirmation"
REASON_FIELD_NAME = "reason"
DISABLED_STATUS = "disabled"
ENABLED_STATUS = "enabled"
CUSTOMER_SERVICE_ROLE = BusinessAdminRoleKey.CUSTOMER_SERVICE.value
BUSINESS_OPERATOR_ROLE = BusinessAdminRoleKey.BUSINESS_OPERATOR.value
ADMIN_GRANT_INVALID_CONFIRMATION = "invalid-admin-grant-confirmation"


class TestAdminUserInterface:
    """
    管理员用户接口测试集合。
    """

    def test_user_query_should_require_admin_token(self) -> None:
        """
        验证用户查询需要管理员访问令牌。
        """

        app = TestAppFactory().create()
        with TestClient(app) as client:
            unauthorized_response = client.get(ADMIN_USERS_PATH)
            access_token = self._issue_admin_token(client)
            authorized_response = client.get(
                ADMIN_USERS_PATH,
                headers=self._build_auth_header(access_token),
            )

        assert unauthorized_response.status_code == HTTPStatus.UNAUTHORIZED
        assert authorized_response.status_code == HTTPStatus.OK

    def test_user_write_should_require_auth_manage_scope(self) -> None:
        """
        验证用户写接口需要 auth:manage。
        """

        username = self._build_username("forbidden")
        subject_id = self._build_subject_id("forbidden")
        app = TestAppFactory().create(
            overrides={
                "auth_module": {
                    "bootstrap_admin": {
                        "enabled": True,
                        "username": ADMIN_USERNAME,
                        "subject_id": DEFAULT_ADMIN_SUBJECT_ID,
                        "role_bindings": [
                            {
                                "kind": "bootstrap_role_binding",
                                "schema_version": "v1",
                                "role_key": AUTH_ADMIN_ROLE,
                                "scope_codes": [AUTH_READ_SCOPE],
                            }
                        ],
                    }
                }
            }
        )

        try:
            with TestClient(app) as client:
                access_token = self._issue_admin_token(client)
                response = client.post(
                    ADMIN_USERS_PATH,
                    headers=self._build_auth_header(access_token),
                    json=self._build_user_create_body(
                        username=username,
                        subject_id=subject_id,
                    ),
                )
        finally:
            self._restore_default_admin_authorization()

        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_user_crud_and_error_status_should_match_contract(self) -> None:
        """
        验证用户 CRUD、密码脱敏以及 404、409、422 状态码。
        """

        username = self._build_username("crud")
        updated_username = self._build_username("updated")
        subject_id = self._build_subject_id("crud")
        duplicate_subject_id = self._build_subject_id("duplicate")
        missing_subject_id = self._build_subject_id("missing")
        app = TestAppFactory().create()
        with TestClient(app) as client:
            access_token = self._issue_admin_token(client)
            auth_header = self._build_auth_header(access_token)
            try:
                create_response = client.post(
                    ADMIN_USERS_PATH,
                    headers=auth_header,
                    json=self._build_user_create_body(
                        username=username,
                        subject_id=subject_id,
                    ),
                )
                duplicate_response = client.post(
                    ADMIN_USERS_PATH,
                    headers=auth_header,
                    json=self._build_user_create_body(
                        username=username,
                        subject_id=duplicate_subject_id,
                    ),
                )
                list_response = client.get(
                    ADMIN_USERS_PATH,
                    headers=auth_header,
                    params={"keyword": username},
                )
                detail_response = client.get(
                    ADMIN_USER_DETAIL_PATH.format(subject_id=subject_id),
                    headers=auth_header,
                )
                update_response = client.patch(
                    ADMIN_USER_DETAIL_PATH.format(subject_id=subject_id),
                    headers=auth_header,
                    json=self._build_user_update_body(username=updated_username),
                )
                role_replace_response = client.post(
                    ADMIN_USER_ROLES_PATH.format(subject_id=subject_id),
                    headers=auth_header,
                    json=self._build_user_role_replace_body(),
                )
                password_response = client.post(
                    ADMIN_USER_PASSWORD_PATH.format(subject_id=subject_id),
                    headers=auth_header,
                    json=self._build_password_reset_body(USER_INTERFACE_NEW_PASSWORD),
                )
                missing_response = client.get(
                    ADMIN_USER_DETAIL_PATH.format(subject_id=missing_subject_id),
                    headers=auth_header,
                )
                invalid_role_response = client.post(
                    ADMIN_USER_ROLES_PATH.format(subject_id=subject_id),
                    headers=auth_header,
                    json=self._build_user_role_replace_body(role_keys=[AuthRoleKey.ADMIN.value]),
                )
                self_lock_response = client.post(
                    ADMIN_USER_ROLES_PATH.format(subject_id=DEFAULT_ADMIN_SUBJECT_ID),
                    headers=auth_header,
                    json=self._build_user_role_replace_body(role_keys=[]),
                )
                invalid_limit_response = client.get(
                    ADMIN_USERS_PATH,
                    headers=auth_header,
                    params={"page_size": INVALID_LIMIT},
                )
                missing_disable_reason_response = client.post(
                    ADMIN_USER_DISABLE_PATH.format(subject_id=subject_id),
                    headers=auth_header,
                    json=self._without_detail_field(
                        self._build_user_disable_body(),
                        REASON_FIELD_NAME,
                    ),
                )
                blank_disable_reason_body = self._build_user_disable_body()
                blank_disable_reason_detail = blank_disable_reason_body[DETAIL_FIELD]
                if not isinstance(blank_disable_reason_detail, dict):
                    raise TypeError("身份管理请求 detail 必须是映射。")
                blank_disable_reason_detail[REASON_FIELD_NAME] = ""
                blank_disable_reason_response = client.post(
                    ADMIN_USER_DISABLE_PATH.format(subject_id=subject_id),
                    headers=auth_header,
                    json=blank_disable_reason_body,
                )
                disable_response = client.post(
                    ADMIN_USER_DISABLE_PATH.format(subject_id=subject_id),
                    headers=auth_header,
                    json=self._build_user_disable_body(),
                )
                disabled_login_response = client.post(
                    AUTH_TOKEN_PATH,
                    json={
                        "username": updated_username,
                        "password": USER_INTERFACE_NEW_PASSWORD,
                    },
                )
                enable_response = client.post(
                    ADMIN_USER_ENABLE_PATH.format(subject_id=subject_id),
                    headers=auth_header,
                    json=self._build_user_enable_body(),
                )
                legacy_delete_response = client.delete(
                    ADMIN_USER_DETAIL_PATH.format(subject_id=subject_id),
                    headers=auth_header,
                )
            finally:
                self._cleanup(
                    app=app,
                    subject_ids=[subject_id, duplicate_subject_id],
                    usernames=[username, updated_username],
                )

        assert create_response.status_code == HTTPStatus.OK
        assert USER_INTERFACE_PASSWORD not in create_response.text
        assert duplicate_response.status_code == HTTPStatus.CONFLICT
        assert list_response.status_code == HTTPStatus.OK
        assert detail_response.status_code == HTTPStatus.OK
        assert detail_response.json()[DATA_FIELD][DETAIL_FIELD][SUBJECT_ID_FIELD] == subject_id
        assert update_response.status_code == HTTPStatus.OK
        assert update_response.json()[DATA_FIELD][DETAIL_FIELD][USERNAME_FIELD] == updated_username
        assert role_replace_response.status_code == HTTPStatus.OK
        assert password_response.status_code == HTTPStatus.OK
        assert USER_INTERFACE_NEW_PASSWORD not in password_response.text
        assert missing_response.status_code == HTTPStatus.NOT_FOUND
        assert invalid_role_response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        assert self_lock_response.status_code == HTTPStatus.CONFLICT
        assert invalid_limit_response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        assert missing_disable_reason_response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        assert blank_disable_reason_response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        assert disable_response.status_code == HTTPStatus.OK
        assert disable_response.json()[DATA_FIELD][DETAIL_FIELD][STATUS_FIELD] == DISABLED_STATUS
        assert disable_response.json()[DATA_FIELD][DETAIL_FIELD][IS_ACTIVE_FIELD] is False
        assert disabled_login_response.status_code == HTTPStatus.UNAUTHORIZED
        assert enable_response.status_code == HTTPStatus.OK
        assert enable_response.json()[DATA_FIELD][DETAIL_FIELD][STATUS_FIELD] == ENABLED_STATUS
        assert legacy_delete_response.status_code == HTTPStatus.METHOD_NOT_ALLOWED

    def test_user_role_replace_when_confirmation_invalid_should_return_422(self) -> None:
        """
        验证用户授权变更缺少或错误二次确认短语时拒绝。
        """

        username = self._build_username("confirm")
        subject_id = self._build_subject_id("confirm")
        app = TestAppFactory().create()
        with TestClient(app) as client:
            access_token = self._issue_admin_token(client)
            auth_header = self._build_auth_header(access_token)
            try:
                create_response = client.post(
                    ADMIN_USERS_PATH,
                    headers=auth_header,
                    json=self._build_user_create_body(
                        username=username,
                        subject_id=subject_id,
                    ),
                )
                missing_confirmation_response = client.post(
                    ADMIN_USER_ROLES_PATH.format(subject_id=subject_id),
                    headers=auth_header,
                    json=self._without_detail_field(
                        self._build_user_role_replace_body(),
                        CONFIRMATION_FIELD_NAME,
                    ),
                )
                invalid_confirmation_body = self._build_user_role_replace_body()
                detail = invalid_confirmation_body[DETAIL_FIELD]
                if not isinstance(detail, dict):
                    raise TypeError("身份管理请求 detail 必须是映射。")
                detail[CONFIRMATION_FIELD_NAME] = ADMIN_GRANT_INVALID_CONFIRMATION
                invalid_confirmation_response = client.post(
                    ADMIN_USER_ROLES_PATH.format(subject_id=subject_id),
                    headers=auth_header,
                    json=invalid_confirmation_body,
                )
            finally:
                self._cleanup(
                    app=app,
                    subject_ids=[subject_id],
                    usernames=[username],
                )

        assert create_response.status_code == HTTPStatus.OK
        assert missing_confirmation_response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        assert invalid_confirmation_response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def _build_username(self, suffix: str) -> str:
        """
        构建用户名。
        """

        return f"interface_user_{suffix}_{uuid4().hex}"

    def _build_subject_id(self, suffix: str) -> str:
        """
        构建主体标识。
        """

        return f"interface-user-{suffix}-{uuid4()}"

    def _build_missing_role_key(self) -> str:
        """
        构建不存在的角色键。
        """

        return f"missing_role_{uuid4().hex}"

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
                "password": USER_INTERFACE_PASSWORD,
                "role_keys": [CUSTOMER_SERVICE_ROLE],
                "subject_id": subject_id,
            },
        }

    def _build_user_update_body(self, *, username: str) -> dict[str, object]:
        """
        构建用户更新请求体。
        """

        return AdminIdentityEnvelope(
            header=AdminIdentityHeader(
                kind=AdminIdentityPayloadKind.USER_UPDATE,
                schema_version=ADMIN_IDENTITY_SCHEMA_VERSION,
                operation_name=AdminIdentityOperationName.USER_UPDATE,
            ),
            detail=AdminUserUpdateRequest(
                username=username,
            ),
        ).model_dump(mode="json")

    def _build_user_role_replace_body(
        self,
        *,
        role_keys: list[str] | None = None,
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
                role_keys=([BUSINESS_OPERATOR_ROLE] if role_keys is None else role_keys),
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
            detail=AdminUserDisableRequest(reason="接口测试停用"),
        ).model_dump(mode="json")

    def _build_user_enable_body(self) -> dict[str, object]:
        """
        构建用户启用请求体。
        """

        return AdminIdentityEnvelope(
            header=AdminIdentityHeader(
                kind=AdminIdentityPayloadKind.USER_ENABLE,
                schema_version=ADMIN_IDENTITY_SCHEMA_VERSION,
                operation_name=AdminIdentityOperationName.USER_ENABLE,
            ),
            detail=AdminUserEnableRequest(reason="接口测试启用"),
        ).model_dump(mode="json")

    def _build_password_reset_body(self, password: str) -> dict[str, object]:
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
                "password": password,
            },
        }

    def _issue_admin_token(self, client: TestClient) -> str:
        """
        签发管理员访问令牌。
        """

        token_response = client.post(
            AUTH_TOKEN_PATH,
            json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
        )
        return str(token_response.json()[DATA_FIELD]["access_token"])

    def _build_auth_header(self, access_token: str) -> dict[str, str]:
        """
        构建认证请求头。
        """

        return {AUTHORIZATION_HEADER: f"{BEARER_PREFIX} {access_token}"}

    def _without_detail_field(
        self,
        body: dict[str, object],
        field_name: str,
    ) -> dict[str, object]:
        """
        从身份管理请求扩展中移除字段。
        """

        detail = body[DETAIL_FIELD]
        if not isinstance(detail, dict):
            raise TypeError("身份管理请求 detail 必须是映射。")
        next_detail = dict(detail)
        next_detail.pop(field_name, None)
        body[DETAIL_FIELD] = next_detail
        return body

    def _restore_default_admin_authorization(self) -> None:
        """
        恢复默认管理员授权。
        """

        app = TestAppFactory().create()
        with TestClient(app):
            return None

    def _cleanup(
        self,
        *,
        app: FastAPI,
        subject_ids: list[str],
        usernames: list[str],
    ) -> None:
        """
        清理测试用户。
        """

        resource_mount = app.state.container.resource_mount
        unit_of_work = resource_mount.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            users = (
                session.query(AuthUserOrmModel)
                .filter(
                    or_(
                        AuthUserOrmModel.subject_id.in_(subject_ids),
                        AuthUserOrmModel.username.in_(usernames),
                    )
                )
                .all()
            )
            for user in users:
                session.delete(user)
            unit_of_work.commit()
        finally:
            unit_of_work.dispose()
