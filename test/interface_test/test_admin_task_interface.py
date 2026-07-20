"""
管理员任务接口测试模块。
"""

from __future__ import annotations

from http import HTTPStatus
from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from src.api.endpoint_admin_task.contract_admin_task import (
    ADMIN_TASK_DISPATCH_KIND,
    ADMIN_TASK_QUERY_LIMIT_MAXIMUM,
    ADMIN_TASK_QUERY_LIMIT_MINIMUM,
    ADMIN_TASK_SCHEMA_VERSION,
    AdminTaskOperationName,
    AdminTaskPayloadKind,
)
from src.api.endpoint_admin_task.route_admin_task import (
    ADMIN_TASK_DISPATCH_PATH,
    ADMIN_TASK_EXECUTION_RECORD_PATH,
    ADMIN_TASK_EXECUTIONS_PATH,
    ADMIN_TASK_REGISTRATIONS_PATH,
    ADMIN_TASK_RUNTIME_PATH,
)
from src.api.fastapi_app_assembler import FastApiAppAssembler
from src.api.testing.demo_task_binding_factory import (
    DEMO_TASK_KIND,
)
from src.api.testing.test_app_factory import TestAppFactory
from src.application.ports.admin_log_query_port import AdminSecurityEventFilter
from src.core.exception_contract.error_code_catalog_contract import CoreErrorCode
from src.core.http_contract.web_bundle_contract import ApplicationModuleName
from src.core.logging_contract.log_writer_contract import LogWriteReason
from src.core.security_contract.security_event_contract import SecurityEventType
from src.core.task_contract.task_execution_record_contract import TaskExecutionStatus
from src.infrastructure.settings.application_settings import AppEnvironment
from src.infrastructure.settings.raw_application_settings import SettingsOverrideMapping
from src.infrastructure.settings.settings_mapping_merger import SettingsMappingMerger
from src.infrastructure.task.task_registration_registry import RegisteredTaskBinding
from src.infrastructure.testing.sqlite_test_engine_factory import SqliteTestEngineFactory

AUTH_TOKEN_PATH = "/auth/token"
AUTHORIZATION_HEADER = "Authorization"
BEARER_PREFIX = "Bearer"
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin"
DATA_FIELD = "data"
DETAIL_FIELD = "detail"
ERROR_CODE_FIELD = "error_code"
RECORDS_FIELD = "records"
REGISTRATIONS_FIELD = "registrations"
TASK_ID_FIELD = "task_id"
JOB_KIND_FIELD = "job_kind"
DEFAULT_JOB_KIND_FIELD = "default_job_kind"
TASK_RUNTIME_MODE_FIELD = "task_runtime_mode"
TASK_BACKEND_FIELD = "task_backend"
TRANSPORT_BACKEND_FIELD = "transport_backend"
CONFIGURED_TRANSPORT_BACKEND_FIELD = "configured_transport_backend"
REGISTRATION_BACKEND_FIELD = "registration_backend"
CURRENT_RUNTIME_BACKEND_FIELD = "current_runtime_backend"
ACTIVE_FOR_CURRENT_RUNTIME_FIELD = "active_for_current_runtime"
KIND_FIELD = "kind"
SCHEMA_VERSION_FIELD = "schema_version"
HEADER_FIELD = "header"
OPERATION_NAME_FIELD = "operation_name"
PAYLOAD_JSON_FIELD = "payload_json"
TASK_DISPATCH_SCOPE = "task:dispatch"
SYSTEM_READ_SCOPE = "system:read"
AUTH_READ_SCOPE = "auth:read"
AUTH_ADMIN_ROLE = "admin"
TEST_PAYLOAD_JSON = '{"kind":"demo_task","schema_version":"1.0","task_id":"demo"}'
INVALID_PAYLOAD_JSON = '{"kind":"demo_task","schema_version":"1.0","extra":true}'
MISSING_TASK_ID = "missing-admin-task-interface"
TASK_EXECUTION_QUERY_LIMIT_SINGLE_RECORD = 1
TASK_EXECUTION_LIMIT_BELOW_MINIMUM = (
    ADMIN_TASK_QUERY_LIMIT_MINIMUM - TASK_EXECUTION_QUERY_LIMIT_SINGLE_RECORD
)
TASK_EXECUTION_LIMIT_ABOVE_MAXIMUM = (
    ADMIN_TASK_QUERY_LIMIT_MAXIMUM + TASK_EXECUTION_QUERY_LIMIT_SINGLE_RECORD
)
AUTHZ_DENIED_SECURITY_EVENT_LIMIT = 20
DISPATCH_FAILURE_DEDUPLICATION_KEY = "dispatch-failure-dedupe-admin-interface"
HANDLER_MISSING_DISPATCH_FAILURE_DEDUPLICATION_KEY = (
    "handler-missing-dispatch-failure-dedupe-admin-interface"
)
TASK_REGISTRY_BINDING_MAP_ATTR = "_binding_by_job_kind"
ADMIN_TASK_DISABLED_ENABLED_MODULES = [
    ApplicationModuleName.HEALTH_PROBE.value,
    ApplicationModuleName.AUTH_ACCESS.value,
    ApplicationModuleName.SYSTEM_OVERVIEW.value,
]
ADMIN_TASK_ENABLED_MODULES = [
    ApplicationModuleName.HEALTH_PROBE.value,
    ApplicationModuleName.AUTH_ACCESS.value,
    ApplicationModuleName.ADMIN_TASK.value,
]


class TestAdminTaskInterface:
    """
    管理员任务接口测试集合。
    """

    def test_task_runtime_should_require_admin_token(self) -> None:
        """
        验证任务运行时查询需要管理员访问令牌。
        """

        app = self._create_admin_task_app()

        with TestClient(app) as client:
            unauthorized_response = client.get(ADMIN_TASK_RUNTIME_PATH)
            access_token = self._issue_admin_token(client)
            authorized_response = client.get(
                ADMIN_TASK_RUNTIME_PATH,
                headers=self._build_auth_header(access_token),
            )

        assert unauthorized_response.status_code == HTTPStatus.UNAUTHORIZED
        assert authorized_response.status_code == HTTPStatus.OK
        runtime_detail = authorized_response.json()[DATA_FIELD][DETAIL_FIELD]
        assert runtime_detail[TASK_RUNTIME_MODE_FIELD] == "local_inline"
        assert runtime_detail[TASK_BACKEND_FIELD] == "local"
        assert runtime_detail[TRANSPORT_BACKEND_FIELD] == "local"
        assert runtime_detail[CONFIGURED_TRANSPORT_BACKEND_FIELD] == "local"
        assert runtime_detail[DEFAULT_JOB_KIND_FIELD] == DEMO_TASK_KIND

    def test_task_query_should_require_system_read_scope(self) -> None:
        """
        验证任务查询接口需要 system:read 作用域。
        """

        app = TestAppFactory().create(
            overrides=self._merge_admin_task_module_overrides(
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
                response = client.get(
                    ADMIN_TASK_RUNTIME_PATH,
                    headers=self._build_auth_header(access_token),
                )
        finally:
            self._restore_default_admin_authorization()

        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_task_query_denied_should_record_security_event(self) -> None:
        """
        验证任务查询授权拒绝会写入安全事件。
        """

        app = TestAppFactory().create(
            overrides=self._merge_admin_task_module_overrides(
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
                response = client.get(
                    ADMIN_TASK_RUNTIME_PATH,
                    headers=self._build_auth_header(access_token),
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

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert any(
            snapshot.security_event is not None
            and snapshot.security_event.header.event_type == SecurityEventType.AUTHZ_DENIED.value
            and snapshot.security_event.header.path == ADMIN_TASK_RUNTIME_PATH
            and snapshot.security_event.header.status_code == HTTPStatus.FORBIDDEN
            for snapshot in security_events
        )

    def test_disabled_admin_task_module_should_not_mount_route(self) -> None:
        """
        验证禁用管理员任务模块后不装配对应路由。
        """

        app = TestAppFactory().create(
            overrides={
                "app": {
                    "modules": {
                        "enabled": ADMIN_TASK_DISABLED_ENABLED_MODULES,
                    }
                }
            }
        )

        with TestClient(app) as client:
            access_token = self._issue_admin_token(client)
            response = client.get(
                ADMIN_TASK_RUNTIME_PATH,
                headers=self._build_auth_header(access_token),
            )

        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_task_registration_and_execution_list_should_return_records(self) -> None:
        """
        验证任务注册列表与执行记录列表可查询。
        """

        app = self._create_admin_task_app()

        with TestClient(app) as client:
            access_token = self._issue_admin_token(client)
            auth_header = self._build_auth_header(access_token)
            dispatch_response = client.post(
                ADMIN_TASK_DISPATCH_PATH,
                headers=auth_header,
                json=self._build_dispatch_request(TEST_PAYLOAD_JSON),
            )
            task_id = dispatch_response.json()[DATA_FIELD][DETAIL_FIELD][TASK_ID_FIELD]
            list_response = client.get(
                ADMIN_TASK_EXECUTIONS_PATH,
                headers=auth_header,
                params={
                    "status": TaskExecutionStatus.SUCCESS.value,
                    JOB_KIND_FIELD: DEMO_TASK_KIND,
                    "limit": TASK_EXECUTION_QUERY_LIMIT_SINGLE_RECORD,
                },
            )
            registration_response = client.get(
                ADMIN_TASK_REGISTRATIONS_PATH,
                headers=auth_header,
            )
            detail_response = client.get(
                ADMIN_TASK_EXECUTION_RECORD_PATH.format(task_id=task_id),
                headers=auth_header,
            )

        assert dispatch_response.status_code == HTTPStatus.OK
        assert list_response.status_code == HTTPStatus.OK
        assert (
            len(list_response.json()[DATA_FIELD][DETAIL_FIELD][RECORDS_FIELD])
            == TASK_EXECUTION_QUERY_LIMIT_SINGLE_RECORD
        )
        assert registration_response.status_code == HTTPStatus.OK
        registrations = registration_response.json()[DATA_FIELD][DETAIL_FIELD][REGISTRATIONS_FIELD]
        assert len(registrations) >= 1
        assert any(
            registration[REGISTRATION_BACKEND_FIELD] == "local"
            and registration[CURRENT_RUNTIME_BACKEND_FIELD] == "local"
            and registration[ACTIVE_FOR_CURRENT_RUNTIME_FIELD] is True
            for registration in registrations
        )
        assert detail_response.status_code == HTTPStatus.OK
        assert detail_response.json()[DATA_FIELD][DETAIL_FIELD][TASK_ID_FIELD] == task_id

    def test_task_detail_missing_and_invalid_payload_should_return_errors(self) -> None:
        """
        验证任务详情不存在与无效载荷会返回错误。
        """

        app = self._create_admin_task_app()

        with TestClient(app) as client:
            access_token = self._issue_admin_token(client)
            auth_header = self._build_auth_header(access_token)
            missing_response = client.get(
                ADMIN_TASK_EXECUTION_RECORD_PATH.format(task_id=MISSING_TASK_ID),
                headers=auth_header,
            )
            invalid_payload_response = client.post(
                ADMIN_TASK_DISPATCH_PATH,
                headers=auth_header,
                json=self._build_dispatch_request(INVALID_PAYLOAD_JSON),
            )

        assert missing_response.status_code == HTTPStatus.NOT_FOUND
        assert invalid_payload_response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_task_execution_list_should_reject_limit_out_of_range(self) -> None:
        """
        验证任务执行记录列表拒绝越界 limit。
        """

        app = self._create_admin_task_app()

        with TestClient(app) as client:
            access_token = self._issue_admin_token(client)
            auth_header = self._build_auth_header(access_token)
            below_minimum_response = client.get(
                ADMIN_TASK_EXECUTIONS_PATH,
                headers=auth_header,
                params={"limit": TASK_EXECUTION_LIMIT_BELOW_MINIMUM},
            )
            above_maximum_response = client.get(
                ADMIN_TASK_EXECUTIONS_PATH,
                headers=auth_header,
                params={"limit": TASK_EXECUTION_LIMIT_ABOVE_MAXIMUM},
            )

        assert below_minimum_response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        assert above_maximum_response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_disabled_task_dispatch_should_fail_without_execution_record(self) -> None:
        """
        验证禁用任务派发失败且不会写入任务执行记录。
        """

        app = FastApiAppAssembler()(
            environment=AppEnvironment.TEST,
            settings_overrides=self._admin_task_module_overrides(),
            database_engine_factory=SqliteTestEngineFactory(),
        )

        with TestClient(app) as client:
            access_token = self._issue_admin_token(client)
            response = client.post(
                ADMIN_TASK_DISPATCH_PATH,
                headers=self._build_auth_header(access_token),
                json=self._build_dispatch_request(
                    TEST_PAYLOAD_JSON,
                    deduplication_key=DISPATCH_FAILURE_DEDUPLICATION_KEY,
                ),
            )
            records = app.state.container.resource_mount.get_task_execution_store().list_records(
                limit=ADMIN_TASK_QUERY_LIMIT_MAXIMUM,
                job_kind=DEMO_TASK_KIND,
            )

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert response.json()[DATA_FIELD][ERROR_CODE_FIELD] == str(CoreErrorCode.CONFIG_INVALID)
        assert all(
            record.header.deduplication_key != DISPATCH_FAILURE_DEDUPLICATION_KEY
            for record in records
        )

    def test_handler_missing_task_dispatch_should_fail_without_execution_record(
        self,
    ) -> None:
        """
        验证 handler 未绑定任务派发失败且不会写入任务执行记录。
        """

        app = self._create_admin_task_app()

        with TestClient(app) as client:
            registry = app.state.container.resource_mount.get_task_registration_registry()
            binding_by_job_kind = cast(
                dict[str, RegisteredTaskBinding[BaseModel]],
                getattr(registry, TASK_REGISTRY_BINDING_MAP_ATTR),
            )
            original_binding = binding_by_job_kind.pop(DEMO_TASK_KIND)
            access_token = self._issue_admin_token(client)
            try:
                response = client.post(
                    ADMIN_TASK_DISPATCH_PATH,
                    headers=self._build_auth_header(access_token),
                    json=self._build_dispatch_request(
                        TEST_PAYLOAD_JSON,
                        deduplication_key=HANDLER_MISSING_DISPATCH_FAILURE_DEDUPLICATION_KEY,
                    ),
                )
                records = (
                    app.state.container.resource_mount.get_task_execution_store().list_records(
                        limit=ADMIN_TASK_QUERY_LIMIT_MAXIMUM,
                        job_kind=DEMO_TASK_KIND,
                    )
                )
            finally:
                binding_by_job_kind[DEMO_TASK_KIND] = original_binding

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json()[DATA_FIELD][ERROR_CODE_FIELD] == str(CoreErrorCode.CONFIG_INVALID)
        assert all(
            record.header.deduplication_key != HANDLER_MISSING_DISPATCH_FAILURE_DEDUPLICATION_KEY
            for record in records
        )

    def test_task_dispatch_should_require_task_dispatch_scope(self) -> None:
        """
        验证任务派发接口需要 task:dispatch 作用域。
        """

        app = TestAppFactory().create(
            overrides=self._merge_admin_task_module_overrides(
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
                                    "scope_codes": [AUTH_READ_SCOPE, SYSTEM_READ_SCOPE],
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
                response = client.post(
                    ADMIN_TASK_DISPATCH_PATH,
                    headers=self._build_auth_header(access_token),
                    json=self._build_dispatch_request(TEST_PAYLOAD_JSON),
                )
        finally:
            self._restore_default_admin_authorization()

        assert response.status_code == HTTPStatus.FORBIDDEN

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

    def _create_admin_task_app(
        self,
        *,
        overrides: SettingsOverrideMapping | None = None,
    ) -> FastAPI:
        """
        创建显式启用管理员任务模块的测试应用。
        """

        return TestAppFactory().create(overrides=self._merge_admin_task_module_overrides(overrides))

    def _admin_task_module_overrides(self) -> SettingsOverrideMapping:
        """
        构建管理员任务模块启用覆盖配置。
        """

        return {
            "app": {
                "modules": {
                    "enabled": ADMIN_TASK_ENABLED_MODULES,
                }
            }
        }

    def _merge_admin_task_module_overrides(
        self,
        overrides: SettingsOverrideMapping | None,
    ) -> SettingsOverrideMapping:
        """
        合并管理员任务模块启用覆盖配置。
        """

        module_overrides = self._admin_task_module_overrides()
        if overrides is None:
            return module_overrides
        return SettingsMappingMerger().merge(module_overrides, overrides)

    def _build_dispatch_request(
        self,
        payload_json: str,
        *,
        deduplication_key: str | None = None,
    ) -> dict[str, object]:
        """
        构建任务派发请求体。
        """

        detail: dict[str, object] = {
            KIND_FIELD: ADMIN_TASK_DISPATCH_KIND,
            SCHEMA_VERSION_FIELD: ADMIN_TASK_SCHEMA_VERSION,
            JOB_KIND_FIELD: DEMO_TASK_KIND,
            PAYLOAD_JSON_FIELD: payload_json,
        }
        if deduplication_key is not None:
            detail["deduplication_key"] = deduplication_key
        return {
            HEADER_FIELD: {
                KIND_FIELD: AdminTaskPayloadKind.DISPATCH.value,
                SCHEMA_VERSION_FIELD: ADMIN_TASK_SCHEMA_VERSION,
                OPERATION_NAME_FIELD: AdminTaskOperationName.DISPATCH.value,
            },
            DETAIL_FIELD: detail,
        }
