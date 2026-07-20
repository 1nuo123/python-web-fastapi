"""
安全 HTTP 接口测试模块。
"""

from __future__ import annotations

from http import HTTPStatus

from fastapi.testclient import TestClient

from src.api.endpoint_admin_log.route_admin_log import (
    ADMIN_LOG_RECORDS_PATH,
    ADMIN_SECURITY_EVENTS_PATH,
)
from src.api.endpoint_admin_settings.route_admin_settings import (
    ADMIN_SETTINGS_RELOAD_CANDIDATE_PATH,
    ADMIN_SETTINGS_RELOAD_PATH,
)
from src.api.endpoint_admin_task.route_admin_task import (
    ADMIN_TASK_DISPATCH_PATH,
    ADMIN_TASK_EXECUTION_RECORD_PATH,
    ADMIN_TASK_EXECUTIONS_PATH,
    ADMIN_TASK_REGISTRATIONS_PATH,
    ADMIN_TASK_RUNTIME_PATH,
)
from src.api.testing.test_app_factory import TestAppFactory
from src.core.exception_contract.error_code_catalog_contract import CoreErrorCode
from src.domain.auth.auth_error_code import AuthErrorCode

AUTH_ME_PATH = "/auth/me"
AUTH_TOKEN_PATH = "/auth/token"
DOCS_PATH = "/docs"
HEALTH_READY_PATH = "/health/ready"
OPENAPI_PATH = "/openapi.json"
REDOC_PATH = "/redoc"
SYSTEM_INFO_PATH = "/system/info"
AUTHORIZATION_HEADER = "Authorization"
BEARER_PREFIX = "Bearer"
DATA_FIELD = "data"
DETAIL_FIELD = "detail"
ERROR_CODE_FIELD = "error_code"
GET_OPERATION_NAME = "get"
INVALID_BEARER_TOKEN = "invalid-token"
SECURITY_FIELD = "security"
READY_STATE_ATTR = "_ready"
KIND_FIELD = "kind"
SCHEMA_VERSION_FIELD = "schema_version"
TITLE_FIELD = "title"
APPLICATION_NAME_FIELD = "application_name"
VERSION_FIELD = "version"
ENVIRONMENT_FIELD = "environment"
ENABLED_MODULES_FIELD = "enabled_modules"
READY_FIELD = "ready"
RESOURCES_FIELD = "resources"
ADMIN_USERS_PATH = "/admin/users"
ADMIN_ROLES_PATH = "/admin/roles"
ADMIN_AUDIT_EVENTS_PATH = "/admin/audit-events"
BUSINESS_ADMIN_OPENAPI_PATHS = [
    ADMIN_USERS_PATH,
    ADMIN_ROLES_PATH,
    ADMIN_AUDIT_EVENTS_PATH,
]
OPS_DISABLED_OPENAPI_PATHS = [
    ADMIN_TASK_EXECUTIONS_PATH,
    ADMIN_TASK_EXECUTION_RECORD_PATH,
    ADMIN_TASK_RUNTIME_PATH,
    ADMIN_TASK_REGISTRATIONS_PATH,
    ADMIN_TASK_DISPATCH_PATH,
    ADMIN_SETTINGS_RELOAD_CANDIDATE_PATH,
    ADMIN_SETTINGS_RELOAD_PATH,
    ADMIN_LOG_RECORDS_PATH,
    ADMIN_SECURITY_EVENTS_PATH,
]


class TestSecurityHttpInterface:
    """
    安全 HTTP 接口测试集合。
    """

    def test_system_info_without_token_should_return_401(self) -> None:
        """
        验证系统信息默认不挂载。
        """

        with TestClient(TestAppFactory().create()) as client:
            response = client.get(SYSTEM_INFO_PATH)

        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_system_info_with_admin_token_should_not_mount_by_default(self) -> None:
        """
        验证管理员令牌也不能访问默认未挂载的系统信息。
        """

        with TestClient(TestAppFactory().create()) as client:
            access_token = self._issue_admin_access_token(client)
            response = client.get(
                SYSTEM_INFO_PATH,
                headers={AUTHORIZATION_HEADER: f"{BEARER_PREFIX} {access_token}"},
            )

        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_health_ready_should_not_return_resource_or_module_detail(self) -> None:
        """
        验证就绪探针不返回资源细节和模块清单。
        """

        with TestClient(TestAppFactory().create()) as client:
            response = client.get(HEALTH_READY_PATH)

        response_payload = response.json()["data"]
        assert response.status_code == HTTPStatus.OK
        assert "resources" not in response_payload
        assert "enabled_modules" not in response_payload
        assert "environment" not in response_payload
        assert "version" not in response_payload

    def test_health_ready_when_resource_not_ready_should_return_503(self) -> None:
        """
        验证就绪探针在资源未就绪时返回 503。
        """

        app = TestAppFactory().create()
        with TestClient(app) as client:
            resource_mount = app.state.container.resource_mount
            original_ready = resource_mount.is_ready()
            try:
                setattr(resource_mount, READY_STATE_ATTR, False)
                response = client.get(HEALTH_READY_PATH)
            finally:
                setattr(resource_mount, READY_STATE_ATTR, original_ready)

        assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
        assert response.json()[DATA_FIELD][ERROR_CODE_FIELD] == str(
            CoreErrorCode.RESOURCE_NOT_READY
        )

    def test_security_headers_should_keep_default_safe_headers(self) -> None:
        """
        验证默认安全头保持开启。
        """

        with TestClient(TestAppFactory().create()) as client:
            response = client.get(HEALTH_READY_PATH)

        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert response.headers["Referrer-Policy"] == "no-referrer"
        assert response.headers["Permissions-Policy"] == (
            "geolocation=(), microphone=(), camera=()"
        )

    def test_openapi_routes_should_remain_available_in_test_environment(self) -> None:
        """
        验证测试环境仍保留文档入口，生产关闭由生产路由表单元测试覆盖。
        """

        with TestClient(TestAppFactory().create()) as client:
            docs_response = client.get(DOCS_PATH)
            redoc_response = client.get(REDOC_PATH)
            openapi_response = client.get(OPENAPI_PATH)

        assert docs_response.status_code == HTTPStatus.OK
        assert redoc_response.status_code == HTTPStatus.OK
        assert openapi_response.status_code == HTTPStatus.OK

    def test_public_route_when_invalid_bearer_should_return_401(self) -> None:
        """
        验证公共路由携带无效 Bearer 时应主动拒绝。
        """

        with TestClient(TestAppFactory().create()) as client:
            response = client.get(
                HEALTH_READY_PATH,
                headers={AUTHORIZATION_HEADER: f"{BEARER_PREFIX} {INVALID_BEARER_TOKEN}"},
            )

        assert response.status_code == HTTPStatus.UNAUTHORIZED
        assert response.json()[DATA_FIELD][ERROR_CODE_FIELD] == str(AuthErrorCode.TOKEN_INVALID)

    def test_openapi_should_mark_protected_routes_with_bearer_security(self) -> None:
        """
        验证受保护路由应在 OpenAPI 中声明 Bearer 安全要求。
        """

        with TestClient(TestAppFactory().create()) as client:
            response = client.get(OPENAPI_PATH)

        paths = response.json()["paths"]
        assert response.status_code == HTTPStatus.OK
        assert paths[AUTH_ME_PATH][GET_OPERATION_NAME][SECURITY_FIELD]
        assert paths[ADMIN_USERS_PATH][GET_OPERATION_NAME][SECURITY_FIELD]

    def test_openapi_should_include_business_admin_routes_only(self) -> None:
        """
        验证 OpenAPI 只生成业务后台管理员路由。
        """

        with TestClient(TestAppFactory().create()) as client:
            response = client.get(OPENAPI_PATH)

        paths = response.json()["paths"]
        assert response.status_code == HTTPStatus.OK
        for admin_path in BUSINESS_ADMIN_OPENAPI_PATHS:
            assert admin_path in paths
        for ops_path in OPS_DISABLED_OPENAPI_PATHS:
            assert ops_path not in paths
        assert SYSTEM_INFO_PATH not in paths

    def _issue_admin_access_token(self, client: TestClient) -> str:
        """
        签发管理员访问令牌。
        """

        token_response = client.post(
            AUTH_TOKEN_PATH,
            json={"username": "admin", "password": "admin"},
        )
        return str(token_response.json()["data"]["access_token"])
