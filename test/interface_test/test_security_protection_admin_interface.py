"""
安全防护管理接口测试模块。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from http import HTTPStatus
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.endpoint_security_protection.contract_security_protection import (
    SecurityIpBlockReleaseRequest,
)
from src.api.endpoint_security_protection.route_security_protection import (
    SECURITY_PROTECTION_IP_BLOCK_PATH,
    SECURITY_PROTECTION_IP_BLOCK_RELEASE_PATH,
    SECURITY_PROTECTION_REQUEST_EXECUTION_NAME,
)
from src.api.testing.test_app_factory import TestAppFactory
from src.core.cache_contract.cache_namespace_contract import CacheNamespace
from src.core.http_contract.web_bundle_contract import ApplicationModuleName
from src.core.security_contract.security_ip_block_contract import (
    SecurityIpBlockReason,
    SecurityIpBlockStatus,
)
from src.infrastructure.cache.cache_key_builder import CacheKeyBuilder
from src.infrastructure.security.ip_block_guard import IP_BLOCK_CACHE_SEGMENT
from src.infrastructure.settings.raw_application_settings import SettingsOverrideMapping
from src.infrastructure.settings.settings_mapping_merger import SettingsMappingMerger

AUTH_TOKEN_PATH = "/auth/token"
AUTHORIZATION_HEADER = "Authorization"
BEARER_PREFIX = "Bearer"
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin"
DATA_FIELD = "data"
RECORD_FIELD = "record"
RECORDS_FIELD = "records"
RECORD_ID_FIELD = "record_id"
STATUS_FIELD = "status"
IP_DIGEST_FIELD = "ip_digest"
KIND_FIELD = "kind"
REASON_FIELD = "reason"
BLOCK_SECONDS_FIELD = "block_seconds"
RELEASED_REASON_FIELD = "released_reason"
IP_BLOCK_CREATE_KIND = "security_ip_block_create"
IP_BLOCK_RELEASE_KIND = "security_ip_block_release"
MANUAL_IP_DIGEST = "1234567890abcdef"
INVALID_IP_DIGEST = "short"
SEQUENCE_IP_DIGEST_PREFIX = "sequence"
MANUAL_BLOCK_SECONDS = 120
RELEASED_REASON = "人工解除"
LIST_IP_BLOCKS_USECASE_NAME = "ListAdminSecurityIpBlocksUsecase"
CREATE_IP_BLOCK_USECASE_NAME = "CreateAdminSecurityIpBlockUsecase"
GET_IP_BLOCK_USECASE_NAME = "GetAdminSecurityIpBlockUsecase"
RELEASE_IP_BLOCK_USECASE_NAME = "ReleaseAdminSecurityIpBlockUsecase"
IP_BLOCK_BRIDGE_USECASE_NAMES = [
    CREATE_IP_BLOCK_USECASE_NAME,
    LIST_IP_BLOCKS_USECASE_NAME,
    GET_IP_BLOCK_USECASE_NAME,
    RELEASE_IP_BLOCK_USECASE_NAME,
]
AUTH_READ_SCOPE = "auth:read"
AUTH_ADMIN_ROLE = "admin"
HTTP_OK = HTTPStatus.OK
HTTP_UNAUTHORIZED = HTTPStatus.UNAUTHORIZED
HTTP_FORBIDDEN = HTTPStatus.FORBIDDEN
HTTP_UNPROCESSABLE_ENTITY = HTTPStatus.UNPROCESSABLE_ENTITY
SECURITY_PROTECTION_ENABLED_MODULES = [
    ApplicationModuleName.HEALTH_PROBE.value,
    ApplicationModuleName.AUTH_ACCESS.value,
    ApplicationModuleName.SECURITY_PROTECTION.value,
]


class TestSecurityProtectionAdminInterface:
    """
    安全防护管理接口测试集合。
    """

    def test_release_request_contract_should_keep_ip_digest_and_reason(self) -> None:
        """
        验证释放请求契约。
        """

        command = SecurityIpBlockReleaseRequest(
            ip_digest=MANUAL_IP_DIGEST,
            released_reason=RELEASED_REASON,
        )

        assert command.ip_digest == MANUAL_IP_DIGEST
        assert command.released_reason == RELEASED_REASON

    def test_ip_block_list_should_require_admin_token(self) -> None:
        """
        验证封禁管理查询接口需要管理员访问令牌。
        """

        app = self._create_security_protection_app(
            overrides={
                "runtime": {
                    "security": {"detail": {"protection": {"ip_block": {"enabled": False}}}}
                }
            }
        )

        with TestClient(app) as client:
            unauthorized_response = client.get(SECURITY_PROTECTION_IP_BLOCK_PATH)
            access_token = self._issue_admin_token(client)
            authorized_response = client.get(
                SECURITY_PROTECTION_IP_BLOCK_PATH,
                headers=self._build_auth_header(access_token),
            )

        assert unauthorized_response.status_code == HTTP_UNAUTHORIZED
        assert authorized_response.status_code == HTTP_OK

    def test_ip_block_crud_should_create_query_release_and_delete_cache(self) -> None:
        """
        验证封禁管理接口支持手动封禁、查询、释放和缓存同步删除。
        """

        app = self._create_security_protection_app()

        with TestClient(app) as client:
            access_token = self._issue_admin_token(client)
            auth_header = self._build_auth_header(access_token)
            create_response = client.post(
                SECURITY_PROTECTION_IP_BLOCK_PATH,
                headers=auth_header,
                json={
                    KIND_FIELD: IP_BLOCK_CREATE_KIND,
                    IP_DIGEST_FIELD: MANUAL_IP_DIGEST,
                    REASON_FIELD: SecurityIpBlockReason.MANUAL.value,
                    BLOCK_SECONDS_FIELD: MANUAL_BLOCK_SECONDS,
                },
            )
            record = create_response.json()[DATA_FIELD][RECORD_FIELD]
            record_id = record[RECORD_ID_FIELD]
            cache_key = self._build_ip_block_cache_key(app, MANUAL_IP_DIGEST)
            cached_before_release = app.state.container.resource_mount.get_cache_store().get_value(
                cache_key
            )
            list_response = client.get(
                SECURITY_PROTECTION_IP_BLOCK_PATH,
                headers=auth_header,
                params={
                    STATUS_FIELD: SecurityIpBlockStatus.ACTIVE.value,
                    IP_DIGEST_FIELD: MANUAL_IP_DIGEST,
                },
            )
            get_response = client.get(
                f"{SECURITY_PROTECTION_IP_BLOCK_PATH}/{record_id}",
                headers=auth_header,
            )
            release_response = client.post(
                SECURITY_PROTECTION_IP_BLOCK_RELEASE_PATH,
                headers=auth_header,
                json={
                    KIND_FIELD: IP_BLOCK_RELEASE_KIND,
                    IP_DIGEST_FIELD: MANUAL_IP_DIGEST,
                    RELEASED_REASON_FIELD: RELEASED_REASON,
                },
            )
            cached_after_release = app.state.container.resource_mount.get_cache_store().get_value(
                cache_key
            )
            released_list_response = client.get(
                SECURITY_PROTECTION_IP_BLOCK_PATH,
                headers=auth_header,
                params={
                    STATUS_FIELD: SecurityIpBlockStatus.RELEASED.value,
                    IP_DIGEST_FIELD: MANUAL_IP_DIGEST,
                },
            )
            repeated_release_response = client.post(
                SECURITY_PROTECTION_IP_BLOCK_RELEASE_PATH,
                headers=auth_header,
                json={
                    KIND_FIELD: IP_BLOCK_RELEASE_KIND,
                    IP_DIGEST_FIELD: MANUAL_IP_DIGEST,
                    RELEASED_REASON_FIELD: RELEASED_REASON,
                },
            )

        assert create_response.status_code == HTTP_OK
        assert record[IP_DIGEST_FIELD] == MANUAL_IP_DIGEST
        assert cached_before_release is not None
        assert list_response.status_code == HTTP_OK
        assert len(list_response.json()[DATA_FIELD][RECORDS_FIELD]) >= 1
        assert get_response.status_code == HTTP_OK
        assert get_response.json()[DATA_FIELD][RECORD_ID_FIELD] == record_id
        assert release_response.status_code == HTTP_OK
        assert release_response.json()[DATA_FIELD]["released"] is True
        assert repeated_release_response.status_code == HTTP_OK
        assert repeated_release_response.json()[DATA_FIELD]["released"] is False
        assert cached_after_release is None
        assert released_list_response.status_code == HTTP_OK
        released_records = released_list_response.json()[DATA_FIELD][RECORDS_FIELD]
        assert any(
            record[STATUS_FIELD] == SecurityIpBlockStatus.RELEASED.value
            and record[IP_DIGEST_FIELD] == MANUAL_IP_DIGEST
            for record in released_records
        )

    def test_ip_block_admin_routes_should_execute_through_request_bridge(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        验证封禁管理接口统一经过请求执行桥接器。
        """

        app = self._create_security_protection_app()
        ip_digest = self._build_sequence_ip_digest()
        observed_execution_names: list[str] = []
        observed_usecase_names: list[str] = []

        with TestClient(app) as client:
            access_token = self._issue_admin_token(client)
            auth_header = self._build_auth_header(access_token)
            bridge = app.state.container.resource_mount.get_request_execution_bridge()
            original_run_sync: Callable[..., Awaitable[object]] = bridge.run_sync

            async def recording_run_sync(
                *,
                execution_name: str,
                callable_object: Callable[..., object],
                **kwargs: object,
            ) -> object:
                usecase_name = self._resolve_callable_owner_name(callable_object)
                if usecase_name in IP_BLOCK_BRIDGE_USECASE_NAMES:
                    observed_execution_names.append(execution_name)
                    observed_usecase_names.append(usecase_name)
                return await original_run_sync(
                    execution_name=execution_name,
                    callable_object=callable_object,
                    **kwargs,
                )

            monkeypatch.setattr(bridge, "run_sync", recording_run_sync)
            create_response = client.post(
                SECURITY_PROTECTION_IP_BLOCK_PATH,
                headers=auth_header,
                json={
                    KIND_FIELD: IP_BLOCK_CREATE_KIND,
                    IP_DIGEST_FIELD: ip_digest,
                    REASON_FIELD: SecurityIpBlockReason.MANUAL.value,
                    BLOCK_SECONDS_FIELD: MANUAL_BLOCK_SECONDS,
                },
            )
            record_id = create_response.json()[DATA_FIELD][RECORD_FIELD][RECORD_ID_FIELD]
            list_response = client.get(
                SECURITY_PROTECTION_IP_BLOCK_PATH,
                headers=auth_header,
                params={
                    STATUS_FIELD: SecurityIpBlockStatus.ACTIVE.value,
                    IP_DIGEST_FIELD: ip_digest,
                },
            )
            get_response = client.get(
                f"{SECURITY_PROTECTION_IP_BLOCK_PATH}/{record_id}",
                headers=auth_header,
            )
            release_response = client.post(
                SECURITY_PROTECTION_IP_BLOCK_RELEASE_PATH,
                headers=auth_header,
                json={
                    KIND_FIELD: IP_BLOCK_RELEASE_KIND,
                    IP_DIGEST_FIELD: ip_digest,
                    RELEASED_REASON_FIELD: RELEASED_REASON,
                },
            )

        assert create_response.status_code == HTTP_OK
        assert list_response.status_code == HTTP_OK
        assert get_response.status_code == HTTP_OK
        assert release_response.status_code == HTTP_OK
        assert observed_execution_names == [
            SECURITY_PROTECTION_REQUEST_EXECUTION_NAME,
            SECURITY_PROTECTION_REQUEST_EXECUTION_NAME,
            SECURITY_PROTECTION_REQUEST_EXECUTION_NAME,
            SECURITY_PROTECTION_REQUEST_EXECUTION_NAME,
        ]
        assert observed_usecase_names == [
            CREATE_IP_BLOCK_USECASE_NAME,
            LIST_IP_BLOCKS_USECASE_NAME,
            GET_IP_BLOCK_USECASE_NAME,
            RELEASE_IP_BLOCK_USECASE_NAME,
        ]

    def test_ip_block_admin_should_require_security_manage_scope(self) -> None:
        """
        验证封禁管理写入口需要安全管理作用域。
        """

        app = TestAppFactory().create(
            overrides=self._merge_security_protection_module_overrides(
                {
                    "auth_module": {
                        "bootstrap_admin": {
                            "enabled": True,
                            "username": ADMIN_USERNAME,
                            "subject_id": "user-admin",
                            "role_bindings": [
                                {
                                    KIND_FIELD: "bootstrap_role_binding",
                                    "schema_version": "v1",
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
                response = client.post(
                    SECURITY_PROTECTION_IP_BLOCK_PATH,
                    headers=self._build_auth_header(access_token),
                    json={
                        KIND_FIELD: IP_BLOCK_CREATE_KIND,
                        IP_DIGEST_FIELD: MANUAL_IP_DIGEST,
                        REASON_FIELD: SecurityIpBlockReason.MANUAL.value,
                        BLOCK_SECONDS_FIELD: MANUAL_BLOCK_SECONDS,
                    },
                )
        finally:
            self._restore_default_admin_authorization()

        assert response.status_code == HTTP_FORBIDDEN

    def test_bootstrap_admin_scope_override_should_not_pollute_next_admin_test(
        self,
    ) -> None:
        """
        验证 bootstrap admin 覆盖用例后默认管理员授权会恢复。
        """

        self.test_ip_block_admin_should_require_security_manage_scope()
        app = self._create_security_protection_app()
        ip_digest = self._build_sequence_ip_digest()

        with TestClient(app) as client:
            access_token = self._issue_admin_token(client)
            auth_header = self._build_auth_header(access_token)
            response = client.post(
                SECURITY_PROTECTION_IP_BLOCK_PATH,
                headers=auth_header,
                json={
                    KIND_FIELD: IP_BLOCK_CREATE_KIND,
                    IP_DIGEST_FIELD: ip_digest,
                    REASON_FIELD: SecurityIpBlockReason.MANUAL.value,
                    BLOCK_SECONDS_FIELD: MANUAL_BLOCK_SECONDS,
                },
            )
            release_response = client.post(
                SECURITY_PROTECTION_IP_BLOCK_RELEASE_PATH,
                headers=auth_header,
                json={
                    KIND_FIELD: IP_BLOCK_RELEASE_KIND,
                    IP_DIGEST_FIELD: ip_digest,
                    RELEASED_REASON_FIELD: RELEASED_REASON,
                },
            )

        assert response.status_code == HTTP_OK
        assert release_response.status_code == HTTP_OK

    def test_ip_block_release_should_reject_invalid_digest(self) -> None:
        """
        验证封禁释放接口会拒绝无效摘要。
        """

        app = self._create_security_protection_app()

        with TestClient(app) as client:
            access_token = self._issue_admin_token(client)
            response = client.post(
                SECURITY_PROTECTION_IP_BLOCK_RELEASE_PATH,
                headers=self._build_auth_header(access_token),
                json={
                    KIND_FIELD: IP_BLOCK_RELEASE_KIND,
                    IP_DIGEST_FIELD: INVALID_IP_DIGEST,
                    RELEASED_REASON_FIELD: RELEASED_REASON,
                },
            )

        assert response.status_code == HTTP_UNPROCESSABLE_ENTITY

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

    def _resolve_callable_owner_name(
        self,
        callable_object: Callable[..., object],
    ) -> str:
        """
        解析桥接器执行的用例名称。
        """

        owner = getattr(callable_object, "__self__", None)
        if owner is None:
            return callable_object.__class__.__name__
        return owner.__class__.__name__

    def _restore_default_admin_authorization(self) -> None:
        """
        恢复默认管理员授权。
        """

        app = TestAppFactory().create()
        with TestClient(app):
            return None

    def _build_sequence_ip_digest(self) -> str:
        """
        构建顺序敏感回归用 IP 摘要。
        """

        return f"{SEQUENCE_IP_DIGEST_PREFIX}{uuid4().hex}"

    def _create_security_protection_app(
        self,
        *,
        overrides: SettingsOverrideMapping | None = None,
    ) -> FastAPI:
        """
        创建显式启用安全防护模块的测试应用。
        """

        return TestAppFactory().create(
            overrides=self._merge_security_protection_module_overrides(overrides)
        )

    def _security_protection_module_overrides(self) -> SettingsOverrideMapping:
        """
        构建安全防护模块启用覆盖配置。
        """

        return {
            "app": {
                "modules": {
                    "enabled": SECURITY_PROTECTION_ENABLED_MODULES,
                }
            }
        }

    def _merge_security_protection_module_overrides(
        self,
        overrides: SettingsOverrideMapping | None,
    ) -> SettingsOverrideMapping:
        """
        合并安全防护模块启用覆盖配置。
        """

        module_overrides = self._security_protection_module_overrides()
        if overrides is None:
            return module_overrides
        return SettingsMappingMerger().merge(module_overrides, overrides)

    def _build_ip_block_cache_key(self, app: FastAPI, ip_digest: str) -> str:
        """
        构建 IP 封禁缓存键。
        """

        settings = app.state.container.settings_holder.current_settings
        return CacheKeyBuilder(key_prefix=settings.runtime.cache.key_prefix).build(
            namespace=CacheNamespace.IP_BLOCK,
            key_parts=[IP_BLOCK_CACHE_SEGMENT, ip_digest],
        )
