"""
业务后台禁用平台控制面接口测试模块。
"""

from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus

from fastapi.testclient import TestClient

from src.api.endpoint_admin_audit.route_admin_audit import ADMIN_AUDIT_EVENTS_PATH
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
from src.api.endpoint_security_protection.route_security_protection import (
    SECURITY_PROTECTION_IP_BLOCK_PATH,
    SECURITY_PROTECTION_IP_BLOCK_RECORD_PATH,
    SECURITY_PROTECTION_IP_BLOCK_RELEASE_PATH,
)
from src.api.testing.test_app_factory import TestAppFactory

OPENAPI_PATH = "/openapi.json"
HEALTH_LIVE_PATH = "/health/live"
SYSTEM_INFO_PATH = "/system/info"
SECURITY_RECORD_ID = "00000000-0000-0000-0000-000000000001"
ALLOWED_ORIGIN = "http://localhost:3000"
REJECTED_ORIGIN = "https://example.invalid"
ACCESS_CONTROL_REQUEST_METHOD_HEADER = "Access-Control-Request-Method"
ACCESS_CONTROL_ALLOW_ORIGIN_HEADER = "access-control-allow-origin"
ORIGIN_HEADER = "Origin"
GET_METHOD = "GET"
POST_METHOD = "POST"
OPTIONS_METHOD = "OPTIONS"
DISABLED_OPENAPI_PATHS = [
    ADMIN_TASK_RUNTIME_PATH,
    ADMIN_TASK_REGISTRATIONS_PATH,
    ADMIN_TASK_DISPATCH_PATH,
    ADMIN_TASK_EXECUTIONS_PATH,
    ADMIN_TASK_EXECUTION_RECORD_PATH,
    ADMIN_SETTINGS_RELOAD_CANDIDATE_PATH,
    ADMIN_SETTINGS_RELOAD_PATH,
    ADMIN_LOG_RECORDS_PATH,
    ADMIN_SECURITY_EVENTS_PATH,
    SECURITY_PROTECTION_IP_BLOCK_PATH,
    SECURITY_PROTECTION_IP_BLOCK_RECORD_PATH,
    SECURITY_PROTECTION_IP_BLOCK_RELEASE_PATH,
    SYSTEM_INFO_PATH,
]
BUSINESS_OPENAPI_PATHS = [
    ADMIN_USERS_PATH,
    ADMIN_USER_DETAIL_PATH,
    ADMIN_USER_DISABLE_PATH,
    ADMIN_USER_ENABLE_PATH,
    ADMIN_USER_PASSWORD_PATH,
    ADMIN_USER_ROLES_PATH,
    ADMIN_ROLES_PATH,
    ADMIN_BUSINESS_ROLES_PATH,
    ADMIN_SCOPES_PATH,
    ADMIN_SCOPE_DETAIL_PATH,
    ADMIN_ROLE_DETAIL_PATH,
    ADMIN_ROLE_SCOPES_PATH,
    ADMIN_AUDIT_EVENTS_PATH,
]


@dataclass(frozen=True, slots=True)
class DisabledRouteCheck:
    """
    默认禁用路由检查项。
    """

    method: str
    path: str


DISABLED_ROUTE_CHECKS: tuple[DisabledRouteCheck, ...] = (
    DisabledRouteCheck(method=GET_METHOD, path=ADMIN_TASK_RUNTIME_PATH),
    DisabledRouteCheck(method=GET_METHOD, path=ADMIN_TASK_REGISTRATIONS_PATH),
    DisabledRouteCheck(method=POST_METHOD, path=ADMIN_TASK_DISPATCH_PATH),
    DisabledRouteCheck(method=GET_METHOD, path=ADMIN_TASK_EXECUTIONS_PATH),
    DisabledRouteCheck(
        method=GET_METHOD,
        path=ADMIN_TASK_EXECUTION_RECORD_PATH.format(task_id=SECURITY_RECORD_ID),
    ),
    DisabledRouteCheck(method=GET_METHOD, path=ADMIN_SETTINGS_RELOAD_CANDIDATE_PATH),
    DisabledRouteCheck(method=POST_METHOD, path=ADMIN_SETTINGS_RELOAD_PATH),
    DisabledRouteCheck(method=GET_METHOD, path=ADMIN_LOG_RECORDS_PATH),
    DisabledRouteCheck(method=GET_METHOD, path=ADMIN_SECURITY_EVENTS_PATH),
    DisabledRouteCheck(method=GET_METHOD, path=SECURITY_PROTECTION_IP_BLOCK_PATH),
    DisabledRouteCheck(
        method=GET_METHOD,
        path=SECURITY_PROTECTION_IP_BLOCK_RECORD_PATH.format(record_id=SECURITY_RECORD_ID),
    ),
    DisabledRouteCheck(
        method=POST_METHOD,
        path=SECURITY_PROTECTION_IP_BLOCK_RELEASE_PATH,
    ),
    DisabledRouteCheck(method=GET_METHOD, path=SYSTEM_INFO_PATH),
)


class TestAdminOpsModulesDisabledInterface:
    """
    业务后台禁用平台控制面接口测试集合。
    """

    def test_openapi_should_not_expose_ops_only_routes_by_default(self) -> None:
        """
        验证默认 OpenAPI 不暴露平台控制面路由。
        """

        with TestClient(TestAppFactory().create()) as client:
            response = client.get(OPENAPI_PATH)

        paths = response.json()["paths"]

        assert response.status_code == HTTPStatus.OK
        for disabled_path in DISABLED_OPENAPI_PATHS:
            assert disabled_path not in paths
        for business_path in BUSINESS_OPENAPI_PATHS:
            assert business_path in paths

    def test_ops_only_routes_should_return_not_found_by_default(self) -> None:
        """
        验证平台控制面路由默认未挂载。
        """

        with TestClient(TestAppFactory().create()) as client:
            responses = [
                client.request(route.method, route.path) for route in DISABLED_ROUTE_CHECKS
            ]

        assert all(response.status_code == HTTPStatus.NOT_FOUND for response in responses)

    def test_cors_should_allow_configured_origin_and_reject_other_origin(self) -> None:
        """
        验证 CORS 允许源与拒绝源行为。
        """

        with TestClient(TestAppFactory().create()) as client:
            allowed_preflight = client.options(
                HEALTH_LIVE_PATH,
                headers={
                    ORIGIN_HEADER: ALLOWED_ORIGIN,
                    ACCESS_CONTROL_REQUEST_METHOD_HEADER: GET_METHOD,
                },
            )
            rejected_preflight = client.options(
                HEALTH_LIVE_PATH,
                headers={
                    ORIGIN_HEADER: REJECTED_ORIGIN,
                    ACCESS_CONTROL_REQUEST_METHOD_HEADER: GET_METHOD,
                },
            )
            rejected_simple = client.get(
                HEALTH_LIVE_PATH,
                headers={ORIGIN_HEADER: REJECTED_ORIGIN},
            )

        assert allowed_preflight.status_code == HTTPStatus.OK
        assert allowed_preflight.headers[ACCESS_CONTROL_ALLOW_ORIGIN_HEADER] == ALLOWED_ORIGIN
        assert rejected_preflight.status_code == HTTPStatus.BAD_REQUEST
        assert ACCESS_CONTROL_ALLOW_ORIGIN_HEADER not in rejected_simple.headers
