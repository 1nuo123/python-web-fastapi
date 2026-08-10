"""普通用户注册接口测试。"""

from __future__ import annotations

from http import HTTPStatus
from uuid import uuid4

from fastapi.testclient import TestClient
from httpx import Response

from src.api.endpoint_auth_access.route_auth_access import (
    AUTH_BROWSER_TOKEN_PATH,
    AUTH_ME_PATH,
    AUTH_REGISTER_PATH,
)
from src.api.testing.test_app_factory import TestAppFactory
from src.domain.auth.auth_error_code import AuthErrorCode
from src.domain.auth.auth_role_key import AuthRoleKey

AUTHORIZATION_HEADER = "Authorization"
BEARER_PREFIX = "Bearer"
ORIGIN_HEADER = "origin"
TEST_ORIGIN = "http://testserver"
REGISTRATION_PASSWORD = "registration-password"
DATA_FIELD = "data"
ERROR_CODE_FIELD = "error_code"
REGISTRATION_RATE_LIMIT = 5
REGISTRATION_RETRY_AFTER_SECONDS = "600"
RETRY_AFTER_HEADER = "retry-after"


class TestUserRegistrationInterface:
    """普通用户注册接口测试集合。"""

    def test_register_should_create_minimum_privilege_login_identity(self) -> None:
        """验证注册后可登录且只拥有普通用户角色。"""

        username = self._build_username()
        app = TestAppFactory().create()
        with TestClient(app) as client:
            register_response = self._register(client, username)
            login_response = client.post(
                AUTH_BROWSER_TOKEN_PATH,
                headers={ORIGIN_HEADER: TEST_ORIGIN},
                json={"username": username, "password": REGISTRATION_PASSWORD},
            )
            access_token = login_response.json()[DATA_FIELD]["access_token"]
            me_response = client.get(
                AUTH_ME_PATH,
                headers={
                    AUTHORIZATION_HEADER: f"{BEARER_PREFIX} {access_token}",
                },
            )

        assert register_response.status_code == HTTPStatus.CREATED
        assert REGISTRATION_PASSWORD not in register_response.text
        assert login_response.status_code == HTTPStatus.OK
        assert me_response.status_code == HTTPStatus.OK
        assert me_response.json()[DATA_FIELD]["roles"] == [AuthRoleKey.REGISTERED_USER.value]
        assert me_response.json()[DATA_FIELD]["scopes"] == []
        assert me_response.json()[DATA_FIELD]["is_admin"] is False

    def test_register_when_username_exists_should_return_conflict(self) -> None:
        """验证重复用户名返回稳定冲突错误。"""

        username = self._build_username()
        app = TestAppFactory().create()
        with TestClient(app) as client:
            first_response = self._register(client, username)
            duplicate_response = self._register(client, username)

        assert first_response.status_code == HTTPStatus.CREATED
        assert duplicate_response.status_code == HTTPStatus.CONFLICT
        assert duplicate_response.json()[DATA_FIELD][ERROR_CODE_FIELD] == str(
            AuthErrorCode.REGISTRATION_USERNAME_CONFLICT
        )

    def test_register_when_disabled_should_return_forbidden(self) -> None:
        """验证配置关闭时公开注册 fail-closed。"""

        app = TestAppFactory().create(
            overrides={
                "auth_module": {
                    "public_registration": {
                        "enabled": False,
                        "default_role_key": AuthRoleKey.REGISTERED_USER.value,
                    }
                }
            }
        )
        with TestClient(app) as client:
            response = self._register(client, self._build_username())

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert response.json()[DATA_FIELD][ERROR_CODE_FIELD] == str(
            AuthErrorCode.REGISTRATION_DISABLED
        )

    def test_register_when_payload_or_origin_invalid_should_reject(self) -> None:
        """验证非法输入和缺失 Origin 均被拒绝。"""

        app = TestAppFactory().create()
        with TestClient(app) as client:
            invalid_payload_response = client.post(
                AUTH_REGISTER_PATH,
                headers={ORIGIN_HEADER: TEST_ORIGIN},
                json={"username": "UPPER", "password": "short"},
            )
            missing_origin_response = client.post(
                AUTH_REGISTER_PATH,
                json={
                    "username": self._build_username(),
                    "password": REGISTRATION_PASSWORD,
                },
            )

        assert invalid_payload_response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        assert missing_origin_response.status_code == HTTPStatus.FORBIDDEN
        assert missing_origin_response.json()[DATA_FIELD][ERROR_CODE_FIELD] == str(
            AuthErrorCode.BROWSER_ORIGIN_FORBIDDEN
        )

    def test_register_when_rate_limit_exceeded_should_return_429(self) -> None:
        """验证公开注册达到 IP 阈值后返回限流契约。"""

        app = TestAppFactory().create(
            overrides={
                "runtime": {
                    "security": {"detail": {"protection": {"ip_block": {"enabled": False}}}}
                }
            }
        )
        with TestClient(app) as client:
            responses = [
                self._register(client, self._build_username())
                for _index in range(REGISTRATION_RATE_LIMIT + 1)
            ]

        assert responses[REGISTRATION_RATE_LIMIT - 1].status_code == HTTPStatus.CREATED
        assert responses[REGISTRATION_RATE_LIMIT].status_code == HTTPStatus.TOO_MANY_REQUESTS
        assert (
            responses[REGISTRATION_RATE_LIMIT].headers[RETRY_AFTER_HEADER]
            == REGISTRATION_RETRY_AFTER_SECONDS
        )

    def _register(self, client: TestClient, username: str) -> Response:
        """提交普通用户注册请求。"""

        return client.post(
            AUTH_REGISTER_PATH,
            headers={ORIGIN_HEADER: TEST_ORIGIN},
            json={"username": username, "password": REGISTRATION_PASSWORD},
        )

    def _build_username(self) -> str:
        """构建相互独立的合法测试用户名。"""

        return f"registration_{uuid4().hex}"
