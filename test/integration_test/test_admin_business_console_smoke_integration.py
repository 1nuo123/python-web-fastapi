"""
业务管理后台冒烟集成测试模块。
"""

from __future__ import annotations

from http import HTTPStatus

import pytest
from fastapi.testclient import TestClient

from src.api.endpoint_admin_audit.route_admin_audit import ADMIN_AUDIT_EVENTS_PATH
from src.api.endpoint_admin_identity.route_admin_identity_common import (
    ADMIN_BUSINESS_ROLES_PATH,
)
from src.api.endpoint_admin_log.route_admin_log import ADMIN_LOG_RECORDS_PATH
from src.api.endpoint_admin_task.route_admin_task import ADMIN_TASK_RUNTIME_PATH
from src.api.testing.test_app_factory import TestAppFactory

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.usefixtures("integration_database"),
]


AUTH_TOKEN_PATH = "/auth/token"
AUTHORIZATION_HEADER = "Authorization"
BEARER_PREFIX = "Bearer"
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin"
DATA_FIELD = "data"
HEALTH_LIVE_PATH = "/health/live"
OPENAPI_PATH = "/openapi.json"
SYSTEM_INFO_PATH = "/system/info"


class TestAdminBusinessConsoleSmokeIntegration:
    """
    业务管理后台冒烟集成测试集合。
    """

    def test_default_business_console_should_start_and_hide_ops_surface(self) -> None:
        """
        验证默认业务后台可启动且隐藏平台控制面。
        """

        with TestClient(TestAppFactory().create()) as client:
            health_response = client.get(HEALTH_LIVE_PATH)
            openapi_response = client.get(OPENAPI_PATH)
            access_token = self._issue_admin_token(client)
            roles_response = client.get(
                ADMIN_BUSINESS_ROLES_PATH,
                headers=self._build_auth_header(access_token),
            )
            audit_response = client.get(
                ADMIN_AUDIT_EVENTS_PATH,
                headers=self._build_auth_header(access_token),
            )

        paths = openapi_response.json()["paths"]

        assert health_response.status_code == HTTPStatus.OK
        assert openapi_response.status_code == HTTPStatus.OK
        assert roles_response.status_code == HTTPStatus.OK
        assert audit_response.status_code == HTTPStatus.OK
        assert ADMIN_BUSINESS_ROLES_PATH in paths
        assert ADMIN_AUDIT_EVENTS_PATH in paths
        assert ADMIN_TASK_RUNTIME_PATH not in paths
        assert ADMIN_LOG_RECORDS_PATH not in paths
        assert SYSTEM_INFO_PATH not in paths

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
