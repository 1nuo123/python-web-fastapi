"""
安全事件接口路径测试模块。
"""

from __future__ import annotations

from http import HTTPStatus

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from src.api.testing.test_app_factory import TestAppFactory
from src.core.http_contract.request_scope_contract import RequestScope
from src.core.logging_contract.log_writer_contract import LogWriteReason
from src.core.security_contract.security_event_contract import SecurityEventType
from src.core.security_contract.token_binding_contract import TokenBindingMode
from src.infrastructure.persistence.orm_model.app_log_record_orm_model import (
    AppLogRecordOrmModel,
)
from src.infrastructure.security.security_event_builder import SecurityEventBuilder

AUTH_TOKEN_PATH = "/auth/token"
AUTH_ME_PATH = "/auth/me"
AUTH_REFRESH_PATH = "/auth/refresh"
SECURITY_LOG_LIMITED_PATH = "/security-log-limited"
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin"
INVALID_USERNAME = "missing-security-user"
INVALID_PASSWORD = "invalid-security-password"
USER_AGENT_HEADER = "User-Agent"
USER_AGENT_VALUE = "SecurityEventHttpTest/1.0"
AUTHORIZATION_HEADER = "Authorization"
BEARER_PREFIX = "Bearer"
DATA_FIELD = "data"
ACCESS_TOKEN_FIELD = "access_token"
REFRESH_TOKEN_FIELD = "refresh_token"
FIRST_CLIENT_ADDRESS = "198.51.100.10"
SECOND_CLIENT_ADDRESS = "198.51.100.11"
TEST_CLIENT_PORT = 50000
SECURITY_LOG_KIND = "security"
DETAIL_JSON_FIELD = "detail_json"
RATE_LIMIT_POLICY_HEADER_KIND = "rate_limit_policy_header"
RATE_LIMIT_POLICY_DETAIL_KIND = "rate_limit_policy"
RATE_LIMIT_POLICY_SCHEMA_VERSION = "1.0"
SECURITY_LOG_RATE_LIMIT_POLICY_NAME = "security_log_rate_limit"
SECURITY_LOG_RATE_LIMIT_LIMIT = 1
SECURITY_LOG_RATE_LIMIT_WINDOW_SECONDS = 60
SECURITY_LOG_RATE_LIMIT_BLOCK_SECONDS = 60
AUTH_FAILURE_LIMIT = 1
HTTP_METHOD_GET = "GET"
OVERSIZED_BODY_LENGTH = 128
OVERSIZED_BODY_CHAR = "x"


class TestSecurityEventHttpInterface:
    """
    安全事件接口路径测试集合。
    """

    def test_security_event_should_build_from_http_request(self) -> None:
        """
        验证 HTTP 请求可构建安全事件。
        """

        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/health/live",
                "headers": [],
                "client": ("127.0.0.1", 12345),
                "scheme": "http",
                "server": ("testserver", 80),
            }
        )
        request.state.request_scope = RequestScope(
            request_id="request-1",
            trace_id="trace-1",
            request_time_epoch=1,
            request_path="/health/live",
            request_method="GET",
        )

        event = SecurityEventBuilder().build_rate_limit_event(
            request=request,
            ip_digest="1234567890abcdef",
            count=2,
            limit=1,
            blocked=True,
        )

        assert event.header.request_id == "request-1"
        assert event.header.trace_id == "trace-1"
        assert event.detail.ip_digest == "1234567890abcdef"

    def test_token_binding_mismatch_should_write_security_log_without_plain_token(
        self,
    ) -> None:
        """
        验证 Token-IP 异常 HTTP 主流程会拒绝、保留原绑定并写入安全日志。
        """

        app = TestAppFactory().create(
            overrides={
                "runtime": {
                    "security": {
                        "detail": {
                            "protection": {
                                "token_binding": {
                                    "enabled": True,
                                    "applicable_paths": [AUTH_ME_PATH],
                                }
                            }
                        }
                    }
                }
            }
        )

        with TestClient(
            app,
            client=(FIRST_CLIENT_ADDRESS, TEST_CLIENT_PORT),
        ) as first_client:
            token_response = first_client.post(
                AUTH_TOKEN_PATH,
                json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
            )
            access_token = token_response.json()[DATA_FIELD][ACCESS_TOKEN_FIELD]
            bound_response = first_client.get(
                AUTH_ME_PATH,
                headers=self._build_auth_header(access_token),
            )
            second_client = TestClient(
                app,
                client=(SECOND_CLIENT_ADDRESS, TEST_CLIENT_PORT),
                raise_server_exceptions=False,
            )
            try:
                mismatch_response = second_client.get(
                    AUTH_ME_PATH,
                    headers=self._build_auth_header(access_token),
                )
                mismatch_retry_response = second_client.get(
                    AUTH_ME_PATH,
                    headers=self._build_auth_header(access_token),
                )
            finally:
                second_client.close()
            rebound_response = first_client.get(
                AUTH_ME_PATH,
                headers=self._build_auth_header(access_token),
            )
            resource_mount = app.state.container.resource_mount
            resource_mount.flush_runtime_logs(reason=LogWriteReason.MANUAL)
            security_logs = self._read_security_logs(app)

        event_payloads = [
            record.detail_json
            for record in security_logs
            if self._read_event_type(record.detail_json)
            == SecurityEventType.TOKEN_BINDING_MISMATCH.value
        ]
        serialized_events = [str(payload) for payload in event_payloads]

        assert token_response.status_code == HTTPStatus.OK
        assert bound_response.status_code == HTTPStatus.OK
        assert mismatch_response.status_code == HTTPStatus.UNAUTHORIZED
        assert mismatch_retry_response.status_code == HTTPStatus.UNAUTHORIZED
        assert rebound_response.status_code == HTTPStatus.OK
        assert len(event_payloads) >= 1
        assert all(access_token not in payload for payload in serialized_events)

    def test_token_binding_disabled_mode_should_skip_binding_guard(self) -> None:
        """
        验证 Token-IP 绑定 disabled 模式不会拒绝跨 IP 自省。
        """

        app = TestAppFactory().create(
            overrides={
                "runtime": {
                    "security": {
                        "detail": {
                            "protection": {
                                "token_binding": {
                                    "enabled": True,
                                    "mode": TokenBindingMode.DISABLED.value,
                                    "applicable_paths": [AUTH_ME_PATH],
                                }
                            }
                        }
                    }
                }
            }
        )

        with TestClient(
            app,
            client=(FIRST_CLIENT_ADDRESS, TEST_CLIENT_PORT),
        ) as first_client:
            before_mismatch_count = self._count_token_binding_mismatch_events(app)
            token_response = first_client.post(
                AUTH_TOKEN_PATH,
                json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
            )
            access_token = token_response.json()[DATA_FIELD][ACCESS_TOKEN_FIELD]
            bound_response = first_client.get(
                AUTH_ME_PATH,
                headers=self._build_auth_header(access_token),
            )
            second_client = TestClient(
                app,
                client=(SECOND_CLIENT_ADDRESS, TEST_CLIENT_PORT),
                raise_server_exceptions=False,
            )
            try:
                second_response = second_client.get(
                    AUTH_ME_PATH,
                    headers=self._build_auth_header(access_token),
                )
            finally:
                second_client.close()
            app.state.container.resource_mount.flush_runtime_logs(reason=LogWriteReason.MANUAL)
            after_mismatch_count = self._count_token_binding_mismatch_events(app)

        assert token_response.status_code == HTTPStatus.OK
        assert bound_response.status_code == HTTPStatus.OK
        assert second_response.status_code == HTTPStatus.OK
        assert after_mismatch_count == before_mismatch_count

    def test_auth_refresh_and_rate_limit_paths_should_write_security_logs(
        self,
    ) -> None:
        """
        验证认证失败、刷新令牌重用和限流路径会写入安全日志且不保留明文敏感值。
        """

        app = TestAppFactory().create(overrides=self._build_security_log_overrides())

        @app.get(SECURITY_LOG_LIMITED_PATH)
        async def limited_endpoint() -> dict[str, bool]:
            return {"ok": True}

        with TestClient(app) as client:
            login_failure_response = client.post(
                AUTH_TOKEN_PATH,
                headers={USER_AGENT_HEADER: USER_AGENT_VALUE},
                json={"username": INVALID_USERNAME, "password": INVALID_PASSWORD},
            )
            login_throttled_response = client.post(
                AUTH_TOKEN_PATH,
                headers={USER_AGENT_HEADER: USER_AGENT_VALUE},
                json={"username": INVALID_USERNAME, "password": INVALID_PASSWORD},
            )
            token_response = client.post(
                AUTH_TOKEN_PATH,
                json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
            )
            refresh_token = token_response.json()[DATA_FIELD][REFRESH_TOKEN_FIELD]
            refresh_response = client.post(
                AUTH_REFRESH_PATH,
                json={"refresh_token": refresh_token},
            )
            refresh_reuse_response = client.post(
                AUTH_REFRESH_PATH,
                json={"refresh_token": refresh_token},
            )
            rate_first_response = client.get(SECURITY_LOG_LIMITED_PATH)
            rate_limited_response = client.get(SECURITY_LOG_LIMITED_PATH)
            app.state.container.resource_mount.flush_runtime_logs(reason=LogWriteReason.MANUAL)
            security_logs = self._read_security_logs(app)

        event_types = {self._read_event_type(record.detail_json) for record in security_logs}
        serialized_logs = [str(record.detail_json) for record in security_logs]

        assert login_failure_response.status_code == HTTPStatus.UNAUTHORIZED
        assert login_throttled_response.status_code == HTTPStatus.TOO_MANY_REQUESTS
        assert token_response.status_code == HTTPStatus.OK
        assert refresh_response.status_code == HTTPStatus.OK
        assert refresh_reuse_response.status_code == HTTPStatus.UNAUTHORIZED
        assert rate_first_response.status_code == HTTPStatus.OK
        assert rate_limited_response.status_code == HTTPStatus.TOO_MANY_REQUESTS
        assert SecurityEventType.AUTH_LOGIN_FAILURE.value in event_types
        assert SecurityEventType.AUTH_LOGIN_THROTTLED.value in event_types
        assert SecurityEventType.AUTH_REFRESH_REUSED.value in event_types
        assert SecurityEventType.RATE_LIMIT_BLOCKED.value in event_types
        assert all(INVALID_PASSWORD not in payload for payload in serialized_logs)
        assert all(refresh_token not in payload for payload in serialized_logs)
        assert all(USER_AGENT_VALUE not in payload for payload in serialized_logs)

    def test_payload_too_large_should_write_security_log(self) -> None:
        """
        验证请求体过大路径会写入安全日志。
        """

        app = TestAppFactory().create(
            overrides={"runtime": {"web": {"max_request_body_bytes": 32}}}
        )

        with TestClient(app) as client:
            response = client.post(
                AUTH_TOKEN_PATH,
                content=OVERSIZED_BODY_CHAR * OVERSIZED_BODY_LENGTH,
                headers={"content-type": "application/json"},
            )
            app.state.container.resource_mount.flush_runtime_logs(reason=LogWriteReason.MANUAL)
            security_logs = self._read_security_logs(app)

        event_types = {self._read_event_type(record.detail_json) for record in security_logs}

        assert response.status_code == HTTPStatus.REQUEST_ENTITY_TOO_LARGE
        assert SecurityEventType.PAYLOAD_TOO_LARGE.value in event_types

    def _build_auth_header(self, access_token: str) -> dict[str, str]:
        """
        构建授权请求头。
        """

        return {AUTHORIZATION_HEADER: f"{BEARER_PREFIX} {access_token}"}

    def _read_security_logs(self, app: FastAPI) -> list[AppLogRecordOrmModel]:
        """
        读取安全日志记录。
        """

        resource_mount = app.state.container.resource_mount
        unit_of_work = resource_mount.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            return list(
                session.query(AppLogRecordOrmModel).filter_by(event_kind=SECURITY_LOG_KIND).all()
            )
        finally:
            unit_of_work.dispose()

    def _read_event_type(self, detail_json: dict[str, object]) -> object:
        """
        从日志扩展字段中读取安全事件类型。
        """

        security_event = detail_json.get("security_event")
        if not isinstance(security_event, dict):
            return None
        header = security_event.get("header")
        if not isinstance(header, dict):
            return None
        return header.get("event_type")

    def _count_token_binding_mismatch_events(self, app: FastAPI) -> int:
        """
        统计 Token-IP 绑定不匹配安全事件数量。
        """

        return len(
            [
                record
                for record in self._read_security_logs(app)
                if self._read_event_type(record.detail_json)
                == SecurityEventType.TOKEN_BINDING_MISMATCH.value
            ]
        )

    def _build_security_log_overrides(self) -> dict[str, object]:
        """
        构造安全事件 HTTP 路径测试覆盖配置。
        """

        return {
            "runtime": {
                "auth": {
                    "issue_access_token_failure_limit": AUTH_FAILURE_LIMIT,
                },
                "security": {
                    "detail": {
                        "protection": {
                            "flow_control": {
                                "policies": [
                                    {
                                        "header": {
                                            "kind": RATE_LIMIT_POLICY_HEADER_KIND,
                                            "schema_version": RATE_LIMIT_POLICY_SCHEMA_VERSION,
                                            "detail_kind": RATE_LIMIT_POLICY_DETAIL_KIND,
                                            "policy_name": SECURITY_LOG_RATE_LIMIT_POLICY_NAME,
                                            "enabled": True,
                                        },
                                        "detail": {
                                            "kind": RATE_LIMIT_POLICY_DETAIL_KIND,
                                            "schema_version": RATE_LIMIT_POLICY_SCHEMA_VERSION,
                                            "path": SECURITY_LOG_LIMITED_PATH,
                                            "method": HTTP_METHOD_GET,
                                            "limit": SECURITY_LOG_RATE_LIMIT_LIMIT,
                                            "window_seconds": SECURITY_LOG_RATE_LIMIT_WINDOW_SECONDS,
                                            "key_dimensions": [
                                                "ip_digest",
                                                "path_method",
                                            ],
                                            "block_when_exceeded": False,
                                            "block_seconds": SECURITY_LOG_RATE_LIMIT_BLOCK_SECONDS,
                                        },
                                    }
                                ]
                            },
                            "ip_block": {"enabled": False},
                        }
                    }
                },
            }
        }
