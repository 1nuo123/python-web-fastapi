"""
管理员配置热更新接口测试模块。
"""

from __future__ import annotations

from http import HTTPStatus

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.endpoint_admin_settings.contract_admin_settings import (
    ADMIN_SETTINGS_RELOAD_REQUEST_KIND,
    ADMIN_SETTINGS_RELOAD_SCHEMA_VERSION,
    AdminSettingsReloadKind,
    AdminSettingsReloadOperationName,
)
from src.api.endpoint_admin_settings.route_admin_settings import (
    ADMIN_SETTINGS_RELOAD_CANDIDATE_PATH,
    ADMIN_SETTINGS_RELOAD_PATH,
)
from src.api.testing.test_app_factory import TestAppFactory
from src.application.ports.admin_log_query_port import AdminSecurityEventFilter
from src.core.http_contract.web_bundle_contract import ApplicationModuleName
from src.core.logging_contract.log_writer_contract import LogWriteReason
from src.core.security_contract.security_event_contract import SecurityEventType
from src.infrastructure.settings.raw_application_settings import SettingsOverrideMapping
from src.infrastructure.settings.settings_mapping_merger import SettingsMappingMerger

AUTH_TOKEN_PATH = "/auth/token"
AUTHORIZATION_HEADER = "Authorization"
BEARER_PREFIX = "Bearer"
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin"
DATA_FIELD = "data"
DETAIL_FIELD = "detail"
HEADER_FIELD = "header"
KIND_FIELD = "kind"
SCHEMA_VERSION_FIELD = "schema_version"
OPERATION_NAME_FIELD = "operation_name"
CANDIDATE_VERSION_FIELD = "candidate_version"
DIGEST_FIELD = "digest"
SUCCESS_FIELD = "success"
OVERRIDES_FIELD = "overrides"
AUTH_READ_SCOPE = "auth:read"
SYSTEM_READ_SCOPE = "system:read"
AUTH_ADMIN_ROLE = "admin"
SYSTEM_READER_ROLE = "system_reader"
AUTHZ_DENIED_SECURITY_EVENT_LIMIT = 20
ADMIN_SETTINGS_DISABLED_ENABLED_MODULES = [
    ApplicationModuleName.HEALTH_PROBE.value,
    ApplicationModuleName.AUTH_ACCESS.value,
    ApplicationModuleName.SYSTEM_OVERVIEW.value,
]
ADMIN_SETTINGS_ENABLED_MODULES = [
    ApplicationModuleName.HEALTH_PROBE.value,
    ApplicationModuleName.AUTH_ACCESS.value,
    ApplicationModuleName.ADMIN_SETTINGS.value,
]


class TestAdminSettingsInterface:
    """
    管理员配置热更新接口测试集合。
    """

    def test_reload_candidate_should_require_admin_token(self) -> None:
        """
        验证配置热更新候选读取需要管理员访问令牌。
        """

        app = self._create_admin_settings_app()

        with TestClient(app) as client:
            unauthorized_response = client.get(ADMIN_SETTINGS_RELOAD_CANDIDATE_PATH)
            access_token = self._issue_admin_token(client)
            authorized_response = client.get(
                ADMIN_SETTINGS_RELOAD_CANDIDATE_PATH,
                headers=self._build_auth_header(access_token),
            )
            stable_response = client.get(
                ADMIN_SETTINGS_RELOAD_CANDIDATE_PATH,
                headers=self._build_auth_header(access_token),
            )

        assert unauthorized_response.status_code == HTTPStatus.UNAUTHORIZED
        assert authorized_response.status_code == HTTPStatus.OK
        assert authorized_response.json()[DATA_FIELD][DETAIL_FIELD][CANDIDATE_VERSION_FIELD] != ""
        assert authorized_response.json()[DATA_FIELD][DETAIL_FIELD][DIGEST_FIELD] != ""
        assert (
            authorized_response.json()[DATA_FIELD][DETAIL_FIELD][DIGEST_FIELD]
            == stable_response.json()[DATA_FIELD][DETAIL_FIELD][DIGEST_FIELD]
        )

    def test_disabled_admin_settings_module_should_not_mount_route(self) -> None:
        """
        验证禁用管理员配置模块后不装配对应路由。
        """

        app = TestAppFactory().create(
            overrides={
                "app": {
                    "modules": {
                        "enabled": ADMIN_SETTINGS_DISABLED_ENABLED_MODULES,
                    }
                }
            }
        )

        with TestClient(app) as client:
            access_token = self._issue_admin_token(client)
            response = client.get(
                ADMIN_SETTINGS_RELOAD_CANDIDATE_PATH,
                headers=self._build_auth_header(access_token),
            )

        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_reload_should_reject_missing_system_read_and_record_event(self) -> None:
        """
        验证配置热更新缺少 system:read 时返回 403 并写入安全事件。
        """

        app = TestAppFactory().create(
            overrides=self._merge_admin_settings_module_overrides(
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
                    ADMIN_SETTINGS_RELOAD_CANDIDATE_PATH,
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
            and snapshot.security_event.header.path == ADMIN_SETTINGS_RELOAD_CANDIDATE_PATH
            and snapshot.security_event.header.status_code == HTTPStatus.FORBIDDEN
            for snapshot in security_events
        )

    def test_reload_should_reject_missing_admin_role(self) -> None:
        """
        验证配置热更新缺少 admin 角色时返回 403。
        """

        app = TestAppFactory().create(
            overrides=self._merge_admin_settings_module_overrides(
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
                response = client.get(
                    ADMIN_SETTINGS_RELOAD_CANDIDATE_PATH,
                    headers=self._build_auth_header(access_token),
                )
        finally:
            self._restore_default_admin_authorization()

        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_reload_should_execute_and_reject_unknown_fields(self) -> None:
        """
        验证热更新接口可执行且拒绝未知字段。
        """

        app = self._create_admin_settings_app()

        with TestClient(app) as client:
            access_token = self._issue_admin_token(client)
            auth_header = self._build_auth_header(access_token)
            invalid_response = client.post(
                ADMIN_SETTINGS_RELOAD_PATH,
                headers=auth_header,
                json=self._build_reload_request(extra_field=True),
            )
            reload_response = client.post(
                ADMIN_SETTINGS_RELOAD_PATH,
                headers=auth_header,
                json=self._build_reload_request(),
            )

        assert reload_response.status_code == HTTPStatus.OK
        assert reload_response.json()[DATA_FIELD][DETAIL_FIELD][SUCCESS_FIELD] is True
        assert invalid_response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

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

    def _create_admin_settings_app(
        self,
        *,
        overrides: SettingsOverrideMapping | None = None,
    ) -> FastAPI:
        """
        创建显式启用管理员配置模块的测试应用。
        """

        return TestAppFactory().create(
            overrides=self._merge_admin_settings_module_overrides(overrides)
        )

    def _admin_settings_module_overrides(self) -> SettingsOverrideMapping:
        """
        构建管理员配置模块启用覆盖配置。
        """

        return {
            "app": {
                "modules": {
                    "enabled": ADMIN_SETTINGS_ENABLED_MODULES,
                }
            }
        }

    def _merge_admin_settings_module_overrides(
        self,
        overrides: SettingsOverrideMapping | None,
    ) -> SettingsOverrideMapping:
        """
        合并管理员配置模块启用覆盖配置。
        """

        module_overrides = self._admin_settings_module_overrides()
        if overrides is None:
            return module_overrides
        return SettingsMappingMerger().merge(module_overrides, overrides)

    def _build_reload_request(self, *, extra_field: bool = False) -> dict[str, object]:
        """
        构建热更新请求体。
        """

        detail: dict[str, object] = {
            KIND_FIELD: ADMIN_SETTINGS_RELOAD_REQUEST_KIND,
            SCHEMA_VERSION_FIELD: ADMIN_SETTINGS_RELOAD_SCHEMA_VERSION,
        }
        if extra_field:
            detail[OVERRIDES_FIELD] = {"runtime": {"logging": {"level": "INFO"}}}
        return {
            HEADER_FIELD: {
                KIND_FIELD: AdminSettingsReloadKind.REQUEST.value,
                SCHEMA_VERSION_FIELD: ADMIN_SETTINGS_RELOAD_SCHEMA_VERSION,
                OPERATION_NAME_FIELD: (AdminSettingsReloadOperationName.APPLY_RELOAD.value),
            },
            DETAIL_FIELD: detail,
        }
