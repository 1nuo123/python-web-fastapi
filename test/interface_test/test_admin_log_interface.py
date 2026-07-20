"""
管理员日志接口测试模块。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.endpoint_admin_log.contract_admin_log import (
    ADMIN_LOG_QUERY_LIMIT_MAXIMUM,
    ADMIN_LOG_QUERY_LIMIT_MINIMUM,
)
from src.api.endpoint_admin_log.route_admin_log import (
    ADMIN_LOG_RECORDS_PATH,
    ADMIN_SECURITY_EVENTS_PATH,
)
from src.api.testing.test_app_factory import TestAppFactory
from src.application.ports.admin_log_query_port import AdminSecurityEventFilter
from src.core.http_contract.runtime_resource_contract import RuntimeResourceStatus
from src.core.http_contract.web_bundle_contract import ApplicationModuleName
from src.core.logging_contract.log_event_contract import (
    AccessLogDetail,
    LogEventEnvelope,
    LogEventHeader,
    LogEventKind,
    LogLevel,
    ResourceLifecycleAction,
    ResourceLifecycleLogDetail,
)
from src.core.logging_contract.log_writer_contract import LogWriteReason
from src.core.security_contract.security_event_contract import (
    AuthFailureSecurityEventDetail,
    SecurityEventDecision,
    SecurityEventEnvelope,
    SecurityEventHeader,
    SecurityEventSeverity,
    SecurityEventType,
)
from src.infrastructure.settings.raw_application_settings import SettingsOverrideMapping
from src.infrastructure.settings.settings_mapping_merger import SettingsMappingMerger

AUTH_TOKEN_PATH = "/auth/token"
AUTH_ME_PATH = "/auth/me"
AUTHORIZATION_HEADER = "Authorization"
BEARER_PREFIX = "Bearer"
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin"
INVALID_USERNAME = "missing-admin-log-user"
INVALID_PASSWORD = "invalid-admin-log-password"
DATA_FIELD = "data"
DETAIL_FIELD = "detail"
RECORDS_FIELD = "records"
EVENTS_FIELD = "events"
EVENT_KIND_FIELD = "event_kind"
LEVEL_FIELD = "level"
SECURITY_EVENT_FIELD = "security_event"
HEADER_FIELD = "header"
EVENT_TYPE_FIELD = "event_type"
KIND_FIELD = "kind"
SCHEMA_VERSION_FIELD = "schema_version"
AUTH_READ_SCOPE = "auth:read"
SYSTEM_READ_SCOPE = "system:read"
AUTH_ADMIN_ROLE = "admin"
SYSTEM_READER_ROLE = "system_reader"
USER_AGENT_HEADER = "User-Agent"
USER_AGENT_VALUE = "AdminLogInterfaceTest/1.0"
CLIENT_ADDRESS = "198.51.100.20"
CLIENT_PORT = 50000
LOG_FILTER_EVENT_ID_PREFIX = "event-admin-log-filter"
LOG_FILTER_REQUEST_ID_PREFIX = "request-admin-log-filter"
LOG_FILTER_TRACE_ID_PREFIX = "trace-admin-log-filter"
LOG_FILTER_OUTSIDE_REQUEST_ID = "request-admin-log-filter-outside"
LOG_FILTER_OUTSIDE_TRACE_ID = "trace-admin-log-filter-outside"
LOG_FILTER_OCCURRED_AT = datetime(2026, 5, 26, 8, 0, 0, tzinfo=UTC)
LOG_FILTER_TIME_WINDOW = timedelta(minutes=5)
LOG_FILTER_LIMIT = 10
LOG_INVALID_LIMIT_BELOW_MINIMUM = ADMIN_LOG_QUERY_LIMIT_MINIMUM - 1
LOG_INVALID_LIMIT_ABOVE_MAXIMUM = ADMIN_LOG_QUERY_LIMIT_MAXIMUM + 1
LOG_REDACTION_RESOURCE_PREFIX = "admin-log-redaction-resource"
LOG_REDACTION_EVENT_ID_PREFIX = "event-admin-log-redaction"
LOG_REDACTION_DETAIL_TEXT = (
    "refresh_token=refresh-token-plain secret_key=secret-key-plain "
    "api_key=api-key-plain password=password-plain"
)
REFRESH_TOKEN_SECRET_VALUE = "refresh-token-plain"
SECRET_KEY_SECRET_VALUE = "secret-key-plain"
API_KEY_SECRET_VALUE = "api-key-plain"
PASSWORD_SECRET_VALUE = "password-plain"
REFRESH_TOKEN_REDACTED_TEXT = "refresh_token=***"
SECRET_KEY_REDACTED_TEXT = "secret_key=***"
API_KEY_REDACTED_TEXT = "api_key=***"
PASSWORD_REDACTED_TEXT = "password=***"
AUTHZ_DENIED_SECURITY_EVENT_LIMIT = 20
ADMIN_LOG_DISABLED_ENABLED_MODULES = [
    ApplicationModuleName.HEALTH_PROBE.value,
    ApplicationModuleName.AUTH_ACCESS.value,
    ApplicationModuleName.SYSTEM_OVERVIEW.value,
]
ADMIN_LOG_ENABLED_MODULES = [
    ApplicationModuleName.HEALTH_PROBE.value,
    ApplicationModuleName.AUTH_ACCESS.value,
    ApplicationModuleName.ADMIN_LOG.value,
]
SECURITY_LIMIT_MATCH_REQUEST_ID = "security-limit-match-request"
SECURITY_LIMIT_OUTSIDE_REQUEST_ID = "security-limit-outside-request"
SECURITY_TEST_TRACE_ID = "security-limit-trace"
SECURITY_TEST_PATH = "/admin/security-test"
SECURITY_TEST_METHOD = "GET"
SECURITY_TEST_POLICY = "admin_log_security_filter_test"
SECURITY_TEST_REASON = "admin_log_security_filter_reason"


class TestAdminLogInterface:
    """
    管理员日志接口测试集合。
    """

    def test_log_records_should_query_and_remove_plain_client_identity(self) -> None:
        """
        验证日志查询接口可查询记录且不暴露完整客户端身份。
        """

        app = self._create_admin_log_app()

        with TestClient(
            app,
            client=(CLIENT_ADDRESS, CLIENT_PORT),
        ) as client:
            access_token = self._issue_admin_token(client)
            auth_header = self._build_auth_header(access_token)
            client.get(
                AUTH_ME_PATH,
                headers={
                    **auth_header,
                    USER_AGENT_HEADER: USER_AGENT_VALUE,
                },
            )
            app.state.container.resource_mount.flush_runtime_logs(reason=LogWriteReason.MANUAL)
            response = client.get(
                ADMIN_LOG_RECORDS_PATH,
                headers=auth_header,
                params={
                    LEVEL_FIELD: LogLevel.INFO.value,
                    EVENT_KIND_FIELD: LogEventKind.ACCESS.value,
                },
            )

        serialized_response = response.text

        assert response.status_code == HTTPStatus.OK
        assert len(response.json()[DATA_FIELD][DETAIL_FIELD][RECORDS_FIELD]) >= 1
        assert CLIENT_ADDRESS not in serialized_response
        assert USER_AGENT_VALUE not in serialized_response

    def test_security_events_should_query_by_event_type(self) -> None:
        """
        验证安全事件查询接口可按事件类型过滤。
        """

        app = self._create_admin_log_app()

        with TestClient(app) as client:
            access_token = self._issue_admin_token(client)
            auth_header = self._build_auth_header(access_token)
            login_failure_response = client.post(
                AUTH_TOKEN_PATH,
                headers={USER_AGENT_HEADER: USER_AGENT_VALUE},
                json={"username": INVALID_USERNAME, "password": INVALID_PASSWORD},
            )
            app.state.container.resource_mount.flush_runtime_logs(reason=LogWriteReason.MANUAL)
            response = client.get(
                ADMIN_SECURITY_EVENTS_PATH,
                headers=auth_header,
                params={EVENT_TYPE_FIELD: SecurityEventType.AUTH_LOGIN_FAILURE.value},
            )

        events = response.json()[DATA_FIELD][DETAIL_FIELD][EVENTS_FIELD]

        assert login_failure_response.status_code == HTTPStatus.UNAUTHORIZED
        assert response.status_code == HTTPStatus.OK
        assert len(events) >= 1
        assert all(
            event[SECURITY_EVENT_FIELD][HEADER_FIELD][EVENT_TYPE_FIELD]
            == SecurityEventType.AUTH_LOGIN_FAILURE.value
            for event in events
        )
        assert INVALID_PASSWORD not in response.text
        assert USER_AGENT_VALUE not in response.text

    def test_security_events_should_filter_before_limit(self) -> None:
        """
        验证安全事件过滤先于 limit 生效。
        """

        app = self._create_admin_log_app()

        with TestClient(app) as client:
            access_token = self._issue_admin_token(client)
            auth_header = self._build_auth_header(access_token)
            app.state.container.resource_mount.emit_security_event(
                self._build_security_event(
                    event_type=SecurityEventType.AUTHZ_DENIED,
                    request_id=SECURITY_LIMIT_MATCH_REQUEST_ID,
                )
            )
            app.state.container.resource_mount.emit_security_event(
                self._build_security_event(
                    event_type=SecurityEventType.AUTH_LOGIN_FAILURE,
                    request_id=SECURITY_LIMIT_OUTSIDE_REQUEST_ID,
                )
            )
            app.state.container.resource_mount.flush_runtime_logs(reason=LogWriteReason.MANUAL)
            response = client.get(
                ADMIN_SECURITY_EVENTS_PATH,
                headers=auth_header,
                params={
                    EVENT_TYPE_FIELD: SecurityEventType.AUTHZ_DENIED.value,
                    "limit": 1,
                },
            )

        events = response.json()[DATA_FIELD][DETAIL_FIELD][EVENTS_FIELD]

        assert response.status_code == HTTPStatus.OK
        assert [event["request_id"] for event in events] == [SECURITY_LIMIT_MATCH_REQUEST_ID]

    def test_log_records_should_filter_by_request_trace_and_time_range(self) -> None:
        """
        验证日志查询接口支持请求、链路与时间范围过滤。
        """

        app = self._create_admin_log_app()
        matched_event_id = f"{LOG_FILTER_EVENT_ID_PREFIX}-matched-{uuid4()}"
        outside_event_id = f"{LOG_FILTER_EVENT_ID_PREFIX}-outside-{uuid4()}"
        request_id = f"{LOG_FILTER_REQUEST_ID_PREFIX}-{uuid4()}"
        trace_id = f"{LOG_FILTER_TRACE_ID_PREFIX}-{uuid4()}"

        with TestClient(app) as client:
            access_token = self._issue_admin_token(client)
            auth_header = self._build_auth_header(access_token)
            self._emit_log_events(
                app,
                events=[
                    self._build_access_log_event(
                        event_id=matched_event_id,
                        request_id=request_id,
                        trace_id=trace_id,
                        occurred_at=LOG_FILTER_OCCURRED_AT,
                    ),
                    self._build_access_log_event(
                        event_id=outside_event_id,
                        request_id=LOG_FILTER_OUTSIDE_REQUEST_ID,
                        trace_id=LOG_FILTER_OUTSIDE_TRACE_ID,
                        occurred_at=LOG_FILTER_OCCURRED_AT - LOG_FILTER_TIME_WINDOW,
                    ),
                ],
            )
            response = client.get(
                ADMIN_LOG_RECORDS_PATH,
                headers=auth_header,
                params={
                    LEVEL_FIELD: LogLevel.INFO.value,
                    EVENT_KIND_FIELD: LogEventKind.ACCESS.value,
                    "request_id": request_id,
                    "trace_id": trace_id,
                    "occurred_from": (LOG_FILTER_OCCURRED_AT - LOG_FILTER_TIME_WINDOW).isoformat(),
                    "occurred_to": (LOG_FILTER_OCCURRED_AT + LOG_FILTER_TIME_WINDOW).isoformat(),
                    "limit": LOG_FILTER_LIMIT,
                },
            )

        records = response.json()[DATA_FIELD][DETAIL_FIELD][RECORDS_FIELD]

        assert response.status_code == HTTPStatus.OK
        assert [record["event_id"] for record in records] == [matched_event_id]

    def test_log_query_should_require_admin_system_read_scope(self) -> None:
        """
        验证日志与安全事件查询接口需要管理员 system:read 权限。
        """

        app = TestAppFactory().create(
            overrides=self._merge_admin_log_module_overrides(
                {
                    "auth_module": {
                        "bootstrap_admin": {
                            "enabled": True,
                            "username": ADMIN_USERNAME,
                            "subject_id": "user-admin",
                            "role_bindings": [
                                {
                                    KIND_FIELD: "bootstrap_role_binding",
                                    SCHEMA_VERSION_FIELD: "v1",
                                    "role_key": AUTH_ADMIN_ROLE,
                                    "scope_codes": [AUTH_READ_SCOPE],
                                }
                            ],
                        }
                    }
                }
            )
        )

        try:
            with TestClient(app) as client:
                access_token = self._issue_admin_token(client)
                auth_header = self._build_auth_header(access_token)
                log_response = client.get(
                    ADMIN_LOG_RECORDS_PATH,
                    headers=auth_header,
                )
                security_response = client.get(
                    ADMIN_SECURITY_EVENTS_PATH,
                    headers=auth_header,
                )
                app.state.container.resource_mount.flush_runtime_logs(reason=LogWriteReason.MANUAL)
                security_events = app.state.container.resource_mount.list_admin_security_events(
                    AdminSecurityEventFilter(
                        event_type=SecurityEventType.AUTHZ_DENIED,
                        severity=None,
                        decision=None,
                        occurred_from=None,
                        occurred_to=None,
                        limit=AUTHZ_DENIED_SECURITY_EVENT_LIMIT,
                    )
                )
        finally:
            self._restore_default_admin_authorization()

        assert log_response.status_code == HTTPStatus.FORBIDDEN
        assert security_response.status_code == HTTPStatus.FORBIDDEN
        assert any(
            snapshot.security_event is not None
            and snapshot.security_event.header.path == ADMIN_LOG_RECORDS_PATH
            and snapshot.security_event.header.status_code == HTTPStatus.FORBIDDEN
            for snapshot in security_events
        )
        assert any(
            snapshot.security_event is not None
            and snapshot.security_event.header.path == ADMIN_SECURITY_EVENTS_PATH
            and snapshot.security_event.header.status_code == HTTPStatus.FORBIDDEN
            for snapshot in security_events
        )

    def test_log_query_should_require_admin_role(self) -> None:
        """
        验证日志与安全事件查询接口需要 admin 角色。
        """

        app = TestAppFactory().create(
            overrides=self._merge_admin_log_module_overrides(
                {
                    "auth_module": {
                        "bootstrap_admin": {
                            "enabled": True,
                            "username": ADMIN_USERNAME,
                            "subject_id": "user-admin",
                            "role_bindings": [
                                {
                                    KIND_FIELD: "bootstrap_role_binding",
                                    SCHEMA_VERSION_FIELD: "v1",
                                    "role_key": SYSTEM_READER_ROLE,
                                    "scope_codes": [SYSTEM_READ_SCOPE],
                                }
                            ],
                        }
                    }
                }
            )
        )

        try:
            with TestClient(app) as client:
                access_token = self._issue_admin_token(client)
                auth_header = self._build_auth_header(access_token)
                log_response = client.get(
                    ADMIN_LOG_RECORDS_PATH,
                    headers=auth_header,
                )
                security_response = client.get(
                    ADMIN_SECURITY_EVENTS_PATH,
                    headers=auth_header,
                )
        finally:
            self._restore_default_admin_authorization()

        assert log_response.status_code == HTTPStatus.FORBIDDEN
        assert security_response.status_code == HTTPStatus.FORBIDDEN

    def test_log_records_without_token_should_return_401(self) -> None:
        """
        验证管理员日志接口未登录访问返回 401。
        """

        with TestClient(self._create_admin_log_app()) as client:
            response = client.get(ADMIN_LOG_RECORDS_PATH)

        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_disabled_admin_log_module_should_not_mount_route(self) -> None:
        """
        验证禁用管理员日志模块后不装配对应路由。
        """

        app = TestAppFactory().create(
            overrides={
                "app": {
                    "modules": {
                        "enabled": ADMIN_LOG_DISABLED_ENABLED_MODULES,
                    }
                }
            }
        )

        with TestClient(app) as client:
            access_token = self._issue_admin_token(client)
            response = client.get(
                ADMIN_LOG_RECORDS_PATH,
                headers=self._build_auth_header(access_token),
            )

        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_log_records_should_redact_refresh_token_secret_and_key_values(self) -> None:
        """
        验证日志查询结果会脱敏刷新令牌、密钥与密码。
        """

        app = self._create_admin_log_app()
        resource_name = f"{LOG_REDACTION_RESOURCE_PREFIX}-{uuid4()}"

        with TestClient(app) as client:
            access_token = self._issue_admin_token(client)
            auth_header = self._build_auth_header(access_token)
            self._emit_log_events(
                app,
                events=[
                    self._build_resource_lifecycle_log_event(
                        event_id=f"{LOG_REDACTION_EVENT_ID_PREFIX}-{uuid4()}",
                        resource_name=resource_name,
                        lifecycle_action=ResourceLifecycleAction.RELOAD,
                        resource_status=RuntimeResourceStatus.READY,
                        detail_text=LOG_REDACTION_DETAIL_TEXT,
                    )
                ],
            )
            response = client.get(
                ADMIN_LOG_RECORDS_PATH,
                headers=auth_header,
                params={
                    LEVEL_FIELD: LogLevel.INFO.value,
                    EVENT_KIND_FIELD: LogEventKind.RESOURCE_LIFECYCLE.value,
                    "limit": ADMIN_LOG_QUERY_LIMIT_MAXIMUM,
                },
            )

        serialized_response = response.text

        assert response.status_code == HTTPStatus.OK
        assert resource_name in serialized_response
        assert REFRESH_TOKEN_SECRET_VALUE not in serialized_response
        assert SECRET_KEY_SECRET_VALUE not in serialized_response
        assert API_KEY_SECRET_VALUE not in serialized_response
        assert PASSWORD_SECRET_VALUE not in serialized_response
        assert REFRESH_TOKEN_REDACTED_TEXT in serialized_response
        assert SECRET_KEY_REDACTED_TEXT in serialized_response
        assert API_KEY_REDACTED_TEXT in serialized_response
        assert PASSWORD_REDACTED_TEXT in serialized_response

    def test_log_records_should_reject_invalid_limit(self) -> None:
        """
        验证日志查询接口拒绝非法 limit。
        """

        app = self._create_admin_log_app()

        with TestClient(app) as client:
            access_token = self._issue_admin_token(client)
            below_minimum_response = client.get(
                ADMIN_LOG_RECORDS_PATH,
                headers=self._build_auth_header(access_token),
                params={"limit": LOG_INVALID_LIMIT_BELOW_MINIMUM},
            )
            above_maximum_response = client.get(
                ADMIN_LOG_RECORDS_PATH,
                headers=self._build_auth_header(access_token),
                params={"limit": LOG_INVALID_LIMIT_ABOVE_MAXIMUM},
            )
            security_above_maximum_response = client.get(
                ADMIN_SECURITY_EVENTS_PATH,
                headers=self._build_auth_header(access_token),
                params={"limit": LOG_INVALID_LIMIT_ABOVE_MAXIMUM},
            )

        assert below_minimum_response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        assert above_maximum_response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        assert security_above_maximum_response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

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
        构建授权请求头。
        """

        return {AUTHORIZATION_HEADER: f"{BEARER_PREFIX} {access_token}"}

    def _restore_default_admin_authorization(self) -> None:
        """
        恢复默认引导管理员授权关系。
        """

        app = TestAppFactory().create()
        with TestClient(app):
            return None

    def _create_admin_log_app(
        self,
        *,
        overrides: SettingsOverrideMapping | None = None,
    ) -> FastAPI:
        """
        创建显式启用管理员日志模块的测试应用。
        """

        return TestAppFactory().create(overrides=self._merge_admin_log_module_overrides(overrides))

    def _admin_log_module_overrides(self) -> SettingsOverrideMapping:
        """
        构建管理员日志模块启用覆盖配置。
        """

        return {
            "app": {
                "modules": {
                    "enabled": ADMIN_LOG_ENABLED_MODULES,
                }
            }
        }

    def _merge_admin_log_module_overrides(
        self,
        overrides: SettingsOverrideMapping | None,
    ) -> SettingsOverrideMapping:
        """
        合并管理员日志模块启用覆盖配置。
        """

        module_overrides = self._admin_log_module_overrides()
        if overrides is None:
            return module_overrides
        return SettingsMappingMerger().merge(module_overrides, overrides)

    def _emit_log_events(
        self,
        app: FastAPI,
        *,
        events: list[LogEventEnvelope],
    ) -> None:
        """
        写入并刷出测试日志事件。
        """

        resource_mount = app.state.container.resource_mount
        for event in events:
            resource_mount.emit_log_event(event)
        resource_mount.flush_runtime_logs(reason=LogWriteReason.MANUAL)

    def _build_access_log_event(
        self,
        *,
        event_id: str,
        request_id: str,
        trace_id: str,
        occurred_at: datetime,
    ) -> LogEventEnvelope:
        """
        构建访问日志事件。
        """

        return LogEventEnvelope(
            header=LogEventHeader(
                event_id=event_id,
                occurred_at=occurred_at,
                level=LogLevel.INFO,
                kind=LogEventKind.ACCESS,
                message="管理员日志过滤测试访问日志。",
                request_id=request_id,
                trace_id=trace_id,
                authenticated_subject_id=ADMIN_USERNAME,
                source_module="interface_test",
                source_component="admin_log_interface",
            ),
            detail=AccessLogDetail(
                request_path=AUTH_ME_PATH,
                request_method="GET",
                status_code=HTTPStatus.OK,
                elapsed_milliseconds=1.0,
                client_ip=CLIENT_ADDRESS,
                user_agent=USER_AGENT_VALUE,
                route_name="admin_log_filter_test",
            ),
        )

    def _build_resource_lifecycle_log_event(
        self,
        *,
        event_id: str,
        resource_name: str,
        lifecycle_action: ResourceLifecycleAction,
        resource_status: RuntimeResourceStatus,
        detail_text: str,
    ) -> LogEventEnvelope:
        """
        构建未经过写入构造器脱敏的资源生命周期日志事件。
        """

        return LogEventEnvelope(
            header=LogEventHeader(
                event_id=event_id,
                occurred_at=datetime.now(UTC),
                level=LogLevel.INFO,
                kind=LogEventKind.RESOURCE_LIFECYCLE,
                message="管理员日志查询侧脱敏测试日志。",
                request_id=None,
                trace_id=None,
                authenticated_subject_id=ADMIN_USERNAME,
                source_module="interface_test",
                source_component="admin_log_interface",
            ),
            detail=ResourceLifecycleLogDetail(
                resource_name=resource_name,
                lifecycle_action=lifecycle_action,
                resource_status=resource_status,
                detail=detail_text,
            ),
        )

    def _build_security_event(
        self,
        *,
        event_type: SecurityEventType,
        request_id: str,
    ) -> SecurityEventEnvelope:
        """
        构建安全事件。
        """

        detail = AuthFailureSecurityEventDetail(
            subject_digest=None,
            ip_digest=None,
            reason_code=SECURITY_TEST_REASON,
        )
        return SecurityEventEnvelope(
            header=SecurityEventHeader(
                event_type=event_type.value,
                detail_kind=detail.kind,
                severity=SecurityEventSeverity.WARNING,
                decision=SecurityEventDecision.DENY,
                reason_code=SECURITY_TEST_REASON,
                request_id=request_id,
                trace_id=SECURITY_TEST_TRACE_ID,
                path=SECURITY_TEST_PATH,
                method=SECURITY_TEST_METHOD,
                status_code=HTTPStatus.FORBIDDEN,
                subject_id=None,
                ip_digest=None,
                user_agent_digest=None,
                policy_name=SECURITY_TEST_POLICY,
            ),
            detail=detail,
        )
