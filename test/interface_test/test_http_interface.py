"""
测试HTTP接口测试模块。
"""

from __future__ import annotations

from http import HTTPStatus
from uuid import uuid4

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from src.api.endpoint_admin_identity.contract_admin_identity_common import (
    ADMIN_IDENTITY_SCHEMA_VERSION,
    AdminIdentityOperationName,
    AdminIdentityPayloadKind,
)
from src.api.endpoint_admin_identity.route_admin_identity_common import ADMIN_USERS_PATH
from src.api.testing.test_app_factory import TestAppFactory
from src.application.ports.admin_identity_port import BusinessAdminRoleKey
from src.core.exception_contract.error_code_catalog_contract import CoreErrorCode
from src.domain.auth.auth_error_code import AuthErrorCode
from src.domain.auth.auth_scope_code import AuthScopeCode
from src.infrastructure.auth import jwt_token_service
from src.infrastructure.persistence.orm_model.auth_role_scope_orm_model import (
    AuthRoleScopeOrmModel,
)
from src.infrastructure.persistence.orm_model.auth_user_orm_model import AuthUserOrmModel

API_PREFIX = "/api/v1"
AUTH_ME_PATH = "/auth/me"
AUTH_REFRESH_PATH = "/auth/refresh"
AUTH_REVOKE_PATH = "/auth/revoke"
AUTH_TOKEN_PATH = "/auth/token"
AUTH_READ_SCOPE_CODE = AuthScopeCode.AUTH_READ.value
AUTH_MANAGE_SCOPE_CODE = AuthScopeCode.AUTH_MANAGE.value
HEALTH_LIVE_PATH = "/health/live"
MIDDLEWARE_TRACE_HEADER = "X-Middleware-Trace"
SYSTEM_INFO_PATH = "/system/info"
AUTHORIZATION_HEADER = "Authorization"
BEARER_PREFIX = "Bearer"
ACCESS_TOKEN_FIELD = "access_token"
DATA_FIELD = "data"
ERROR_CODE_FIELD = "error_code"
REFRESH_TOKEN_FIELD = "refresh_token"
SCOPES_FIELD = "scopes"
IS_ADMIN_FIELD = "is_admin"
BUSINESS_AUTH_ME_PASSWORD = "business-auth-me-password"
CUSTOMER_SERVICE_ROLE = BusinessAdminRoleKey.CUSTOMER_SERVICE.value
BUSINESS_OPERATOR_ROLE = BusinessAdminRoleKey.BUSINESS_OPERATOR.value
EXPIRED_ACCESS_TOKEN_EPOCH = 4_102_444_800
OPENAPI_PATHS_FIELD = "paths"
OPENAPI_GET_METHOD = "get"
OPENAPI_RESPONSES_FIELD = "responses"
OPENAPI_SUCCESS_STATUS = "200"
OPENAPI_CONTENT_FIELD = "content"
OPENAPI_JSON_MEDIA_TYPE = "application/json"
OPENAPI_SCHEMA_FIELD = "schema"
OPENAPI_REF_FIELD = "$ref"
OPENAPI_COMPONENTS_FIELD = "components"
OPENAPI_SCHEMAS_FIELD = "schemas"
OPENAPI_PROPERTIES_FIELD = "properties"
OPENAPI_ADDITIONAL_PROPERTIES_FIELD = "additionalProperties"
AUTH_ME_RESPONSE_SCHEMA_REF = "#/components/schemas/ResponseEnvelope_AuthenticatedPrincipal_"
AUTHENTICATED_PRINCIPAL_SCHEMA_NAME = "AuthenticatedPrincipal"
AUTHENTICATED_PRINCIPAL_OPENAPI_FIELDS = frozenset(
    {
        "kind",
        "schema_version",
        "subject_id",
        "username",
        "roles",
        "scopes",
        IS_ADMIN_FIELD,
    }
)


class TestHttpInterface:
    """
    测试HTTP接口测试集合，用于组织同一主题下的测试场景。
    """

    def test_health_live_should_return_success(self) -> None:
        """
        验证健康存活应返回成功。

        :returns: 无返回值。
        :rtype: None
        """

        with TestClient(TestAppFactory().create()) as client:
            response = client.get(HEALTH_LIVE_PATH)
            assert response.status_code == 200
            assert response.json()["data"]["kind"] == "health_probe"

    def test_system_info_should_not_mount_by_default(self) -> None:
        """
        验证系统信息默认不进入业务后台暴露面。

        :returns: 无返回值。
        :rtype: None
        """

        with TestClient(TestAppFactory().create()) as client:
            response = client.get(SYSTEM_INFO_PATH)
            assert response.status_code == HTTPStatus.NOT_FOUND

    def test_auth_token_should_issue_tokens(self) -> None:
        """
        验证鉴权令牌应签发令牌集合。

        :returns: 无返回值。
        :rtype: None
        """

        with TestClient(TestAppFactory().create()) as client:
            response = client.post(
                AUTH_TOKEN_PATH,
                json={"username": "admin", "password": "admin"},
            )
            assert response.status_code == 200
            assert response.json()["data"]["kind"] == "token_issue"

    def test_auth_refresh_should_issue_new_tokens(self) -> None:
        """
        验证鉴权刷新应签发新令牌集合。

        :returns: 无返回值。
        :rtype: None
        """

        with TestClient(TestAppFactory().create()) as client:
            token_response = client.post(
                AUTH_TOKEN_PATH,
                json={"username": "admin", "password": "admin"},
            )
            refresh_response = client.post(
                AUTH_REFRESH_PATH,
                json={"refresh_token": token_response.json()["data"]["refresh_token"]},
            )
            assert refresh_response.status_code == 200
            assert refresh_response.json()["data"]["kind"] == "token_issue"

    def test_auth_refresh_when_reused_should_revoke_current_session(self) -> None:
        """
        验证鉴权刷新当旧令牌被复用应撤销当前会话。

        :returns: 无返回值。
        :rtype: None
        """

        with TestClient(TestAppFactory().create()) as client:
            token_response = client.post(
                AUTH_TOKEN_PATH,
                json={"username": "admin", "password": "admin"},
            )
            refresh_token = token_response.json()[DATA_FIELD][REFRESH_TOKEN_FIELD]
            first_refresh_response = client.post(
                AUTH_REFRESH_PATH,
                json={REFRESH_TOKEN_FIELD: refresh_token},
            )
            refreshed_access_token = first_refresh_response.json()[DATA_FIELD][ACCESS_TOKEN_FIELD]
            refreshed_refresh_token = first_refresh_response.json()[DATA_FIELD][REFRESH_TOKEN_FIELD]
            reused_response = client.post(
                AUTH_REFRESH_PATH,
                json={REFRESH_TOKEN_FIELD: refresh_token},
            )
            revoked_access_response = client.get(
                AUTH_ME_PATH,
                headers={AUTHORIZATION_HEADER: f"{BEARER_PREFIX} {refreshed_access_token}"},
            )
            revoked_refresh_response = client.post(
                AUTH_REFRESH_PATH,
                json={REFRESH_TOKEN_FIELD: refreshed_refresh_token},
            )

            assert first_refresh_response.status_code == HTTPStatus.OK
            assert reused_response.status_code == HTTPStatus.UNAUTHORIZED
            assert reused_response.json()[DATA_FIELD][ERROR_CODE_FIELD] == str(
                AuthErrorCode.TOKEN_REUSED
            )
            assert revoked_access_response.status_code == HTTPStatus.UNAUTHORIZED
            assert revoked_access_response.json()[DATA_FIELD][ERROR_CODE_FIELD] == str(
                AuthErrorCode.TOKEN_REVOKED
            )
            assert revoked_refresh_response.status_code == HTTPStatus.UNAUTHORIZED
            assert revoked_refresh_response.json()[DATA_FIELD][ERROR_CODE_FIELD] == str(
                AuthErrorCode.TOKEN_REVOKED
            )

    def test_auth_revoke_should_return_revoked_payload(self) -> None:
        """
        验证鉴权撤销应返回已撤销载荷。

        :returns: 无返回值。
        :rtype: None
        """

        with TestClient(TestAppFactory().create()) as client:
            token_response = client.post(
                AUTH_TOKEN_PATH,
                json={"username": "admin", "password": "admin"},
            )
            revoke_response = client.post(
                AUTH_REVOKE_PATH,
                json={"refresh_token": token_response.json()["data"]["refresh_token"]},
            )
            assert revoke_response.status_code == 200
            assert revoke_response.json()["data"]["kind"] == "token_revoke"
            assert revoke_response.json()["data"]["revoked"] is True

    def test_auth_me_when_session_revoked_should_return_401(self) -> None:
        """
        验证鉴权当前主体当会话已撤销应返回401。

        :returns: 无返回值。
        :rtype: None
        """

        with TestClient(TestAppFactory().create()) as client:
            token_response = client.post(
                AUTH_TOKEN_PATH,
                json={"username": "admin", "password": "admin"},
            )
            access_token = token_response.json()["data"]["access_token"]
            refresh_token = token_response.json()["data"]["refresh_token"]
            client.post(
                AUTH_REVOKE_PATH,
                json={"refresh_token": refresh_token},
            )
            response = client.get(
                AUTH_ME_PATH,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            assert response.status_code == 401
            assert response.json()["data"]["error_code"] == "auth.token.revoked"

    def test_auth_token_when_payload_exceeds_limit_should_return_413_envelope(self) -> None:
        """
        验证鉴权令牌当载荷超出限制应返回413信封。

        :returns: 无返回值。
        :rtype: None
        """

        app = TestAppFactory().create(overrides={"runtime": {"web": {"max_request_body_bytes": 8}}})
        with TestClient(app) as client:
            response = client.post(
                AUTH_TOKEN_PATH,
                json={"username": "admin", "password": "admin"},
            )
            assert response.status_code == HTTPStatus.REQUEST_ENTITY_TOO_LARGE
            assert response.json()["data"]["kind"] == "http_fault"
            assert response.json()["data"]["error_code"] == str(
                CoreErrorCode.REQUEST_PAYLOAD_TOO_LARGE
            )

    def test_health_live_when_api_prefix_configured_should_use_prefixed_path(self) -> None:
        """
        验证健康存活当API前缀已配置应用途带前缀路径。

        :returns: 无返回值。
        :rtype: None
        """

        app = TestAppFactory().create(overrides={"runtime": {"web": {"api_prefix": API_PREFIX}}})
        with TestClient(app) as client:
            legacy_response = client.get(HEALTH_LIVE_PATH)
            prefixed_response = client.get(f"{API_PREFIX}{HEALTH_LIVE_PATH}")
            assert legacy_response.status_code == 404
            assert prefixed_response.status_code == 200
            assert prefixed_response.json()["data"]["kind"] == "health_probe"

    def test_health_live_when_access_log_disabled_should_remove_access_log_trace(self) -> None:
        """
        验证健康存活当访问日志禁用应移除访问日志跟踪。

        :returns: 无返回值。
        :rtype: None
        """

        enabled_app = TestAppFactory().create(
            overrides={"runtime": {"web": {"include_middleware_trace_header": True}}}
        )
        disabled_app = TestAppFactory().create(
            overrides={
                "runtime": {
                    "web": {
                        "enable_access_log": False,
                        "include_middleware_trace_header": True,
                    }
                }
            }
        )
        with TestClient(enabled_app) as enabled_client:
            enabled_response = enabled_client.get(HEALTH_LIVE_PATH)
        with TestClient(disabled_app) as disabled_client:
            disabled_response = disabled_client.get(HEALTH_LIVE_PATH)
        assert "access_log" in enabled_response.headers[MIDDLEWARE_TRACE_HEADER]
        assert "access_log" not in disabled_response.headers[MIDDLEWARE_TRACE_HEADER]

    def test_auth_token_when_missing_field_should_return_422(self) -> None:
        """
        验证鉴权令牌当缺失字段应返回422。

        :returns: 无返回值。
        :rtype: None
        """

        with TestClient(TestAppFactory().create()) as client:
            response = client.post(AUTH_TOKEN_PATH, json={"username": "admin"})
            assert response.status_code == 422
            assert response.json()["data"]["kind"] == "http_fault"

    def test_auth_token_when_password_invalid_should_return_401(self) -> None:
        """
        验证鉴权令牌当密码无效应返回401。

        :returns: 无返回值。
        :rtype: None
        """

        with TestClient(TestAppFactory().create()) as client:
            response = client.post(
                AUTH_TOKEN_PATH,
                json={"username": "admin", "password": "wrong-password"},
            )
            assert response.status_code == 401
            assert response.json()["data"]["error_code"] == "auth.access.invalid_credentials"

    def test_auth_me_when_bearer_scheme_is_lowercase_should_return_200(self) -> None:
        """
        验证鉴权当前主体当Bearer方案是否小写应返回200。

        :returns: 无返回值。
        :rtype: None
        """

        with TestClient(TestAppFactory().create()) as client:
            token_response = client.post(
                AUTH_TOKEN_PATH,
                json={"username": "admin", "password": "admin"},
            )
            access_token = token_response.json()["data"]["access_token"]
            response = client.get(
                AUTH_ME_PATH,
                headers={"Authorization": f"bearer {access_token}"},
            )
            assert response.status_code == 200

    def test_auth_me_without_token_should_return_401(self) -> None:
        """
        验证鉴权当前主体不带令牌应返回401。

        :returns: 无返回值。
        :rtype: None
        """

        with TestClient(TestAppFactory().create()) as client:
            response = client.get(AUTH_ME_PATH)
            assert response.status_code == 401
            assert response.json()["data"]["error_code"] == "auth.token.invalid"

    def test_auth_me_when_scope_revoked_from_database_should_return_current_subject(
        self,
    ) -> None:
        """
        验证当前主体自省不再要求管理员 auth:read 授权。

        :returns: 无返回值。
        :rtype: None
        """

        app = TestAppFactory().create()
        with TestClient(app) as client:
            token_response = client.post(
                AUTH_TOKEN_PATH,
                json={"username": "admin", "password": "admin"},
            )
            access_token = token_response.json()["data"]["access_token"]
            self._revoke_admin_scope(app)
            try:
                response = client.get(
                    AUTH_ME_PATH,
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                assert response.status_code == HTTPStatus.OK
                assert AUTH_READ_SCOPE_CODE not in response.json()[DATA_FIELD][SCOPES_FIELD]
            finally:
                self._restore_admin_scope(app)

    def test_auth_me_should_allow_business_role_self_introspection(self) -> None:
        """
        验证非管理员业务角色可读取当前主体但不能访问管理接口。
        """

        username = self._build_username("business")
        subject_id = self._build_subject_id("business")
        app = TestAppFactory().create()
        with TestClient(app) as client:
            admin_token_response = client.post(
                AUTH_TOKEN_PATH,
                json={"username": "admin", "password": "admin"},
            )
            admin_token = admin_token_response.json()[DATA_FIELD][ACCESS_TOKEN_FIELD]
            try:
                create_response = client.post(
                    ADMIN_USERS_PATH,
                    headers={
                        AUTHORIZATION_HEADER: f"{BEARER_PREFIX} {admin_token}",
                    },
                    json=self._build_business_user_create_body(
                        username=username,
                        subject_id=subject_id,
                    ),
                )
                token_response = client.post(
                    AUTH_TOKEN_PATH,
                    json={
                        "username": username,
                        "password": BUSINESS_AUTH_ME_PASSWORD,
                    },
                )
                access_token = token_response.json()[DATA_FIELD][ACCESS_TOKEN_FIELD]
                me_response = client.get(
                    AUTH_ME_PATH,
                    headers={
                        AUTHORIZATION_HEADER: f"{BEARER_PREFIX} {access_token}",
                    },
                )
                admin_response = client.get(
                    ADMIN_USERS_PATH,
                    headers={
                        AUTHORIZATION_HEADER: f"{BEARER_PREFIX} {access_token}",
                    },
                )
            finally:
                self._delete_subject_ids(app=app, subject_ids=[subject_id])

        assert create_response.status_code == HTTPStatus.OK
        assert token_response.status_code == HTTPStatus.OK
        assert me_response.status_code == HTTPStatus.OK
        assert me_response.json()[DATA_FIELD]["subject_id"] == subject_id
        assert CUSTOMER_SERVICE_ROLE in me_response.json()[DATA_FIELD]["roles"]
        assert AUTH_READ_SCOPE_CODE in me_response.json()[DATA_FIELD][SCOPES_FIELD]
        assert AUTH_MANAGE_SCOPE_CODE not in me_response.json()[DATA_FIELD][SCOPES_FIELD]
        assert me_response.json()[DATA_FIELD][IS_ADMIN_FIELD] is False
        assert admin_response.status_code == HTTPStatus.FORBIDDEN

    def test_auth_me_should_allow_business_operator_self_introspection(self) -> None:
        """
        验证 business_operator 可读取当前主体并保持管理员接口禁止访问。
        """

        username = self._build_username("business_operator")
        subject_id = self._build_subject_id("business-operator")
        app = TestAppFactory().create()
        with TestClient(app) as client:
            admin_token_response = client.post(
                AUTH_TOKEN_PATH,
                json={"username": "admin", "password": "admin"},
            )
            admin_token = admin_token_response.json()[DATA_FIELD][ACCESS_TOKEN_FIELD]
            try:
                create_response = client.post(
                    ADMIN_USERS_PATH,
                    headers={
                        AUTHORIZATION_HEADER: f"{BEARER_PREFIX} {admin_token}",
                    },
                    json=self._build_business_user_create_body(
                        username=username,
                        subject_id=subject_id,
                        role_key=BUSINESS_OPERATOR_ROLE,
                    ),
                )
                token_response = client.post(
                    AUTH_TOKEN_PATH,
                    json={
                        "username": username,
                        "password": BUSINESS_AUTH_ME_PASSWORD,
                    },
                )
                access_token = token_response.json()[DATA_FIELD][ACCESS_TOKEN_FIELD]
                me_response = client.get(
                    AUTH_ME_PATH,
                    headers={
                        AUTHORIZATION_HEADER: f"{BEARER_PREFIX} {access_token}",
                    },
                )
                admin_response = client.get(
                    ADMIN_USERS_PATH,
                    headers={
                        AUTHORIZATION_HEADER: f"{BEARER_PREFIX} {access_token}",
                    },
                )
            finally:
                self._delete_subject_ids(app=app, subject_ids=[subject_id])

        assert create_response.status_code == HTTPStatus.OK
        assert token_response.status_code == HTTPStatus.OK
        assert me_response.status_code == HTTPStatus.OK
        assert me_response.json()[DATA_FIELD]["subject_id"] == subject_id
        assert BUSINESS_OPERATOR_ROLE in me_response.json()[DATA_FIELD]["roles"]
        assert AUTH_READ_SCOPE_CODE in me_response.json()[DATA_FIELD][SCOPES_FIELD]
        assert AUTH_MANAGE_SCOPE_CODE not in me_response.json()[DATA_FIELD][SCOPES_FIELD]
        assert me_response.json()[DATA_FIELD][IS_ADMIN_FIELD] is False
        assert admin_response.status_code == HTTPStatus.FORBIDDEN

    def test_auth_me_when_access_token_expired_should_return_401(
        self,
        monkeypatch: MonkeyPatch,
    ) -> None:
        """
        验证 /auth/me 对过期 access token 返回认证失败。
        """

        with TestClient(TestAppFactory().create()) as client:
            token_response = client.post(
                AUTH_TOKEN_PATH,
                json={"username": "admin", "password": "admin"},
            )
            access_token = token_response.json()[DATA_FIELD][ACCESS_TOKEN_FIELD]
            monkeypatch.setattr(
                jwt_token_service.time,
                "time",
                lambda: EXPIRED_ACCESS_TOKEN_EPOCH,
            )
            response = client.get(
                AUTH_ME_PATH,
                headers={AUTHORIZATION_HEADER: f"{BEARER_PREFIX} {access_token}"},
            )

        assert response.status_code == HTTPStatus.UNAUTHORIZED
        assert response.json()[DATA_FIELD][ERROR_CODE_FIELD] == str(AuthErrorCode.TOKEN_EXPIRED)

    def test_auth_me_openapi_should_expose_authenticated_principal_schema(
        self,
    ) -> None:
        """
        验证 /auth/me OpenAPI 应暴露当前用户自省响应字段全集。
        """

        app = TestAppFactory().create()
        openapi_schema = app.openapi()
        auth_me_response_schema = openapi_schema[OPENAPI_PATHS_FIELD][AUTH_ME_PATH][
            OPENAPI_GET_METHOD
        ][OPENAPI_RESPONSES_FIELD][OPENAPI_SUCCESS_STATUS][OPENAPI_CONTENT_FIELD][
            OPENAPI_JSON_MEDIA_TYPE
        ][OPENAPI_SCHEMA_FIELD]
        principal_schema = openapi_schema[OPENAPI_COMPONENTS_FIELD][OPENAPI_SCHEMAS_FIELD][
            AUTHENTICATED_PRINCIPAL_SCHEMA_NAME
        ]

        assert auth_me_response_schema[OPENAPI_REF_FIELD] == AUTH_ME_RESPONSE_SCHEMA_REF
        assert (
            set(principal_schema[OPENAPI_PROPERTIES_FIELD])
            == AUTHENTICATED_PRINCIPAL_OPENAPI_FIELDS
        )
        assert principal_schema[OPENAPI_ADDITIONAL_PROPERTIES_FIELD] is False

    def _build_username(self, suffix: str) -> str:
        """
        构建测试用户名。
        """

        return f"http_{suffix}_{uuid4().hex}"

    def _build_subject_id(self, suffix: str) -> str:
        """
        构建测试主体标识。
        """

        return f"http-{suffix}-{uuid4()}"

    def _build_business_user_create_body(
        self,
        *,
        username: str,
        subject_id: str,
        role_key: str = CUSTOMER_SERVICE_ROLE,
    ) -> dict[str, object]:
        """
        构建业务角色用户创建请求体。
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
                "password": BUSINESS_AUTH_ME_PASSWORD,
                "role_keys": [role_key],
                "subject_id": subject_id,
            },
        }

    def _delete_subject_ids(self, *, app, subject_ids: list[str]) -> None:
        """
        删除测试主体。
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

    def _revoke_admin_scope(self, app) -> None:
        """
        撤销管理员作用域。

        :param app: 当前 FastAPI 或 ASGI 应用实例。
        :type app: Any
        :returns: 无返回值。
        :rtype: None
        """

        resource_mount = app.state.container.resource_mount
        unit_of_work = resource_mount.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            user = session.query(AuthUserOrmModel).filter_by(username="admin").one()
            admin_role = next(
                user_role.role
                for user_role in user.user_roles
                if user_role.role.role_key == "admin"
            )
            admin_role.role_scopes[:] = [
                role_scope
                for role_scope in admin_role.role_scopes
                if role_scope.scope_code != AUTH_READ_SCOPE_CODE
            ]
            unit_of_work.commit()
        finally:
            unit_of_work.dispose()

    def _restore_admin_scope(self, app) -> None:
        """
        处理恢复管理员作用域。

        :param app: 当前 FastAPI 或 ASGI 应用实例。
        :type app: Any
        :returns: 无返回值。
        :rtype: None
        """

        resource_mount = app.state.container.resource_mount
        unit_of_work = resource_mount.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            user = session.query(AuthUserOrmModel).filter_by(username="admin").one()
            admin_role = next(
                user_role.role
                for user_role in user.user_roles
                if user_role.role.role_key == "admin"
            )
            if (
                session.get(
                    AuthRoleScopeOrmModel,
                    (admin_role.role_id, AUTH_READ_SCOPE_CODE),
                )
                is not None
            ):
                return
            admin_role.role_scopes.append(AuthRoleScopeOrmModel(scope_code=AUTH_READ_SCOPE_CODE))
            unit_of_work.commit()
        finally:
            unit_of_work.dispose()
