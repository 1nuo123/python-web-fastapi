"""
测试运行时路径测试模块。
"""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.testing.demo_task_binding_factory import (
    DEMO_TASK_KIND,
    DemoTaskPayload,
)
from src.api.testing.test_app_factory import TestAppFactory
from src.application.dispatch_background_job_usecase import TaskDispatchCommand
from src.application.issue_access_token_usecase import CredentialInput
from src.core.auth_contract.authenticated_principal_contract import AuthenticatedPrincipal
from src.core.auth_contract.token_payload_contract import TokenUse
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.http_contract.runtime_resource_contract import RuntimeResourceStatus
from src.core.task_contract.task_dispatcher_contract import TaskDispatchResultPayload
from src.domain.auth.auth_error_code import AuthErrorCode
from src.domain.auth.auth_role_key import AuthRoleKey
from src.domain.auth.auth_scope_code import AuthScopeCode
from src.infrastructure.auth.password_hasher import PasswordHasher
from src.infrastructure.fastapi_middleware_plan import FastApiMiddlewarePlan
from src.infrastructure.middleware_chain.authentication_binding_middleware import (
    AuthenticationBindingMiddleware,
)
from src.infrastructure.middleware_chain.payload_guard_middleware import (
    PayloadGuardMiddleware,
)
from src.infrastructure.middleware_chain.rate_limit_middleware import RateLimitMiddleware
from src.infrastructure.middleware_chain.security_header_middleware import (
    SecurityHeaderMiddleware,
)
from src.infrastructure.resource_mount.shared_resource_constants import (
    RESOURCE_HTTP_CLIENT,
    RESOURCE_TASK,
)
from src.infrastructure.settings.app_settings_loader import AppSettingsLoader
from src.infrastructure.settings.application_settings import AppEnvironment
from src.infrastructure.settings.settings_reload_coordinator import (
    ReloadResultPayload,
    SettingsReloadCoordinator,
)
from src.infrastructure.shared_resource_mount import SharedResourceMount

API_PREFIX = "/api/v1"
AUTHORIZATION_HEADER = "Authorization"
AUTH_ME_PATH = "/auth/me"
AUTH_REFRESH_PATH = "/auth/refresh"
AUTH_TOKEN_PATH = "/auth/token"
BEARER_PREFIX = "Bearer"
DATA_FIELD = "data"
ERROR_CODE_FIELD = "error_code"
REFRESH_TOKEN_FIELD = "refresh_token"
ACCESS_TOKEN_FIELD = "access_token"
CONCURRENT_RUNTIME_WORKER_COUNT = 4
CONCURRENT_RUNTIME_TIMEOUT_SECONDS = 10
CONCURRENT_RUNTIME_RELOAD_BODY_LIMIT = 8192
EXPECTED_SINGLE_RUNTIME_BACKEND_COUNT = 1


class TestRuntimePath:
    """
    测试运行时路径测试集合，用于组织同一主题下的测试场景。
    """

    def test_middleware_plan_should_keep_expected_order(self) -> None:
        """
        验证中间件计划应保持预期顺序。

        :returns: 无返回值。
        :rtype: None
        """

        app = TestAppFactory().create()
        container = app.state.container
        bindings = FastApiMiddlewarePlan().build_bindings(
            resource_mount=container.resource_mount,
            logger=container.resource_mount._logger,  # noqa: SLF001
        )
        binding_names = [binding.cls.__name__ for binding in bindings]
        assert binding_names == [
            "CORSMiddleware",
            "RequestScopeMiddleware",
            "PayloadGuardMiddleware",
            "AuthenticationBindingMiddleware",
            "RateLimitMiddleware",
            "SecurityHeaderMiddleware",
            "AccessLogMiddleware",
            "ElapsedProbeMiddleware",
        ]
        runtime_binding_types = {
            PayloadGuardMiddleware,
            AuthenticationBindingMiddleware,
            RateLimitMiddleware,
            SecurityHeaderMiddleware,
        }
        runtime_bindings = [binding for binding in bindings if binding.cls in runtime_binding_types]
        assert all("resource_mount" in binding.kwargs for binding in runtime_bindings)
        assert all("settings_holder" not in binding.kwargs for binding in runtime_bindings)

    def test_middleware_plan_when_access_log_disabled_should_omit_access_log(self) -> None:
        """
        验证中间件计划当访问日志禁用应省略访问日志。

        :returns: 无返回值。
        :rtype: None
        """

        app = TestAppFactory().create(overrides={"runtime": {"web": {"enable_access_log": False}}})
        container = app.state.container
        bindings = FastApiMiddlewarePlan().build_bindings(
            resource_mount=container.resource_mount,
            logger=container.resource_mount._logger,  # noqa: SLF001
        )
        binding_names = [binding.cls.__name__ for binding in bindings]
        assert "AccessLogMiddleware" not in binding_names

    def test_loader_when_api_prefix_missing_leading_slash_should_fail(self) -> None:
        """
        验证加载器当API前缀缺失前导斜杠应失败。

        :returns: 无返回值。
        :rtype: None
        """

        loader = AppSettingsLoader()
        with pytest.raises(HttpFaultException) as fault:
            loader.load_from_mapping(
                environment=AppEnvironment.TEST,
                overrides={"runtime": {"web": {"api_prefix": "api/v1"}}},
            )
        assert "runtime.web.api_prefix 必须为空或以 / 开头" in str(fault.value.detail)

    def test_loader_when_api_prefix_has_trailing_slash_should_normalize(self) -> None:
        """
        验证加载器当API前缀具有尾随斜杠应规范化。

        :returns: 无返回值。
        :rtype: None
        """

        settings = AppSettingsLoader().load_from_mapping(
            environment=AppEnvironment.TEST,
            overrides={"runtime": {"web": {"api_prefix": f"{API_PREFIX}/"}}},
        )
        assert settings.runtime.web.api_prefix == API_PREFIX

    def test_loader_when_api_prefix_is_root_slash_should_normalize_to_empty(self) -> None:
        """
        验证加载器当API前缀是否根斜杠应规范化到空值。

        :returns: 无返回值。
        :rtype: None
        """

        settings = AppSettingsLoader().load_from_mapping(
            environment=AppEnvironment.TEST,
            overrides={"runtime": {"web": {"api_prefix": "/"}}},
        )
        assert settings.runtime.web.api_prefix == ""

    def test_auth_me_when_token_valid_should_success(self) -> None:
        """
        验证鉴权当前主体当令牌有效应成功。

        :returns: 无返回值。
        :rtype: None
        """

        app = TestAppFactory().create()
        with TestClient(app) as client:
            token_response = client.post(
                "/auth/token",
                json={"username": "admin", "password": "admin"},
            )
            access_token = token_response.json()["data"]["access_token"]
            me_response = client.get(
                "/auth/me",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            assert me_response.status_code == 200
            assert me_response.json()["data"]["subject_id"] == "user-admin"

    def test_auth_me_when_session_revoked_should_fail(self) -> None:
        """
        验证鉴权当前主体当会话已撤销应失败。

        :returns: 无返回值。
        :rtype: None
        """

        app = TestAppFactory().create()
        with TestClient(app) as client:
            token_response = client.post(
                "/auth/token",
                json={"username": "admin", "password": "admin"},
            )
            access_token = token_response.json()["data"]["access_token"]
            refresh_token = token_response.json()["data"]["refresh_token"]
            revoke_response = client.post(
                "/auth/revoke",
                json={"refresh_token": refresh_token},
            )
            me_response = client.get(
                "/auth/me",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            assert revoke_response.status_code == 200
            assert me_response.status_code == 401
            assert me_response.json()["data"]["error_code"] == "auth.token.revoked"

    def test_auth_me_when_token_invalid_should_fail(self) -> None:
        """
        验证鉴权当前主体当令牌无效应失败。

        :returns: 无返回值。
        :rtype: None
        """

        app = TestAppFactory().create()
        with TestClient(app) as client:
            me_response = client.get(
                "/auth/me",
                headers={"Authorization": "Bearer invalid-token"},
            )
            assert me_response.status_code == 401
            assert me_response.json()["data"]["error_code"] == "auth.token.invalid"

    def test_reload_when_allowed_field_changed_should_success(self) -> None:
        """
        验证重载当允许字段变更应成功。

        :returns: 无返回值。
        :rtype: None
        """

        app = TestAppFactory().create()
        with TestClient(app):
            coordinator = app.state.container.reload_coordinator
            result = coordinator.reload_from_mapping(
                environment=AppEnvironment.TEST,
                overrides={"runtime": {"web": {"max_request_body_bytes": 2048}}},
            )
        assert result.success is True

    def test_reload_when_restart_required_field_changed_should_reject(self) -> None:
        """
        验证重载当重启必需字段变更应拒绝。

        :returns: 无返回值。
        :rtype: None
        """

        app = TestAppFactory().create()
        coordinator = app.state.container.reload_coordinator
        result = coordinator.reload_from_mapping(
            environment=AppEnvironment.TEST,
            overrides={"runtime": {"database": {"pool_size": 9}}},
        )
        assert result.success is False
        assert "必须重启" in str(result.reason)

    def test_reload_when_cache_backend_detail_changed_should_reject(self) -> None:
        """
        验证重载当缓存后端详情变更应拒绝。

        :returns: 无返回值。
        :rtype: None
        """

        app = TestAppFactory().create()
        coordinator = app.state.container.reload_coordinator
        result = coordinator.reload_from_mapping(
            environment=AppEnvironment.TEST,
            overrides={
                "runtime": {
                    "cache": {
                        "backend_detail": {
                            "kind": "memory_cache_backend",
                            "schema_version": "1.0",
                            "max_entries": 2048,
                        }
                    }
                }
            },
        )
        assert result.success is False
        assert "必须重启" in str(result.reason)
        assert "runtime.cache.backend_detail.max_entries" in str(result.reason)

    def test_reload_when_bootstrap_admin_role_bindings_changed_should_reject(
        self,
    ) -> None:
        """
        验证重载当引导管理员角色绑定集合变更应拒绝。

        :returns: 无返回值。
        :rtype: None
        """

        app = TestAppFactory().create()
        coordinator = app.state.container.reload_coordinator
        result = coordinator.reload_from_mapping(
            environment=AppEnvironment.TEST,
            overrides={
                "auth_module": {
                    "bootstrap_admin": {
                        "enabled": True,
                        "username": "admin",
                        "subject_id": "user-admin",
                        "role_bindings": [
                            {
                                "kind": "bootstrap_role_binding",
                                "schema_version": "v1",
                                "role_key": "admin",
                                "scope_codes": [
                                    "auth:read",
                                    "task:dispatch",
                                    "system:read",
                                ],
                            },
                            {
                                "kind": "bootstrap_role_binding",
                                "schema_version": "v1",
                                "role_key": "auditor",
                                "scope_codes": ["auth:read"],
                            },
                        ],
                    }
                }
            },
        )
        assert result.success is False
        assert "必须重启" in str(result.reason)
        assert "modules.auth.bootstrap_admin.role_bindings" in str(result.reason)

    def test_reload_when_change_not_allowed_should_reject_before_apply(self) -> None:
        """
        验证热更新当变更不允许应在应用前拒绝。
        """

        app = TestAppFactory().create()
        coordinator = app.state.container.reload_coordinator
        original_snapshot = coordinator._snapshot_store.load_latest()  # noqa: SLF001
        assert original_snapshot is not None

        result = coordinator.reload_from_mapping(
            environment=AppEnvironment.TEST,
            overrides={"runtime": {"web": {"api_prefix": "/v2"}}},
        )

        assert result.success is False
        assert result.rolled_back is False
        assert result.active_snapshot_id is None
        assert "不允许热更新" in str(result.reason)
        latest_snapshot = coordinator._snapshot_store.load_latest()  # noqa: SLF001
        assert latest_snapshot is not None
        assert latest_snapshot.version_id == original_snapshot.version_id

    def test_reload_when_apply_failed_should_rollback_and_restore_snapshot(
        self, monkeypatch
    ) -> None:
        """
        验证热更新当应用失败应回滚并恢复旧快照。
        """

        app = TestAppFactory().create()
        resource_mount = app.state.container.resource_mount
        coordinator = app.state.container.reload_coordinator
        original_snapshot_id = coordinator.build_candidate(AppEnvironment.TEST).candidate_version
        with TestClient(app):
            original_http_resource = resource_mount.get_http_client()
            original_update_level = resource_mount._logger_factory.update_level  # noqa: SLF001
            failure_state = {"raised": False}

            def failing_update_level(logger, level_name: str) -> None:
                original_update_level(logger, level_name)
                if not failure_state["raised"]:
                    failure_state["raised"] = True
                    raise RuntimeError("模拟切换失败")

            monkeypatch.setattr(
                resource_mount._logger_factory,  # noqa: SLF001
                "update_level",
                failing_update_level,
            )

            result = coordinator.reload_from_mapping(
                environment=AppEnvironment.TEST,
                overrides={"runtime": {"web": {"max_request_body_bytes": 4096}}},
            )

            assert result.success is False
            assert result.rolled_back is True
            assert result.active_snapshot_id == original_snapshot_id
            assert result.restored_resources == [
                "shared_http_client",
                "shared_async_http_client",
                "shared_task_dispatcher",
            ]
            assert resource_mount.get_http_client() is original_http_resource
            assert resource_mount.get_task_dispatcher() is not None

    def test_reload_when_apply_success_should_keep_runtime_resources_ready(self) -> None:
        """
        验证热更新成功后运行时资源应保持就绪。
        """

        app = TestAppFactory().create()
        resource_mount = app.state.container.resource_mount
        coordinator = app.state.container.reload_coordinator

        with TestClient(app):
            initial_runtime_generation = resource_mount._runtime_bundle.generation  # noqa: SLF001
            result = coordinator.reload_from_mapping(
                environment=AppEnvironment.TEST,
                overrides={"runtime": {"web": {"max_request_body_bytes": 4096}}},
            )
            states = {state.resource_name: state for state in resource_mount.get_runtime_states()}
            runtime_generation = resource_mount._runtime_bundle.generation  # noqa: SLF001

            assert result.success is True
            assert runtime_generation > initial_runtime_generation
            assert resource_mount.get_http_client() is not None
            assert resource_mount.get_task_dispatcher() is not None
            assert states[RESOURCE_HTTP_CLIENT].status == RuntimeResourceStatus.READY
            assert states[RESOURCE_TASK].status == RuntimeResourceStatus.READY

    def test_reload_should_keep_concurrent_dispatch_and_reads_consistent(
        self,
    ) -> None:
        """
        验证热更新并发任务分发与公开读取保持运行时快照一致。
        """

        app = TestAppFactory().create()
        with TestClient(app):
            resource_mount = app.state.container.resource_mount
            coordinator = app.state.container.reload_coordinator
            start_barrier = Barrier(CONCURRENT_RUNTIME_WORKER_COUNT)
            with ThreadPoolExecutor(max_workers=CONCURRENT_RUNTIME_WORKER_COUNT) as executor:
                reload_future = executor.submit(
                    self._reload_runtime_limit,
                    coordinator=coordinator,
                    start_barrier=start_barrier,
                )
                dispatch_future = executor.submit(
                    self._dispatch_default_task,
                    app=app,
                    start_barrier=start_barrier,
                )
                read_futures: list[Future[bool]] = [
                    executor.submit(
                        self._read_runtime_bundle_consistency,
                        resource_mount=resource_mount,
                        start_barrier=start_barrier,
                    )
                    for _ in range(CONCURRENT_RUNTIME_WORKER_COUNT - 2)
                ]

                reload_result = reload_future.result(timeout=CONCURRENT_RUNTIME_TIMEOUT_SECONDS)
                dispatch_result = dispatch_future.result(timeout=CONCURRENT_RUNTIME_TIMEOUT_SECONDS)
                read_results = [
                    future.result(timeout=CONCURRENT_RUNTIME_TIMEOUT_SECONDS)
                    for future in read_futures
                ]

            states = {state.resource_name: state for state in resource_mount.get_runtime_states()}
            runtime_bundle = resource_mount.read_runtime_bundle()

        assert reload_result.success is True
        assert dispatch_result.dispatched is True
        assert dispatch_result.job_kind == DEMO_TASK_KIND
        assert all(read_results)
        assert (
            runtime_bundle.settings.runtime.web.max_request_body_bytes
            == CONCURRENT_RUNTIME_RELOAD_BODY_LIMIT
        )
        assert runtime_bundle.task_accessor.dispatcher is not None
        assert states[RESOURCE_HTTP_CLIENT].status == RuntimeResourceStatus.READY
        assert states[RESOURCE_TASK].status == RuntimeResourceStatus.READY

    def test_auth_refresh_then_reuse_should_follow_rotation_path(self) -> None:
        """
        验证鉴权刷新随后重复使用应遵循轮换路径。

        :returns: 无返回值。
        :rtype: None
        """

        app = TestAppFactory().create()
        with TestClient(app) as client:
            token_response = client.post(
                AUTH_TOKEN_PATH,
                json={"username": "admin", "password": "admin"},
            )
            refresh_token = token_response.json()[DATA_FIELD][REFRESH_TOKEN_FIELD]
            refresh_response = client.post(
                AUTH_REFRESH_PATH,
                json={REFRESH_TOKEN_FIELD: refresh_token},
            )
            refreshed_payload = refresh_response.json()[DATA_FIELD]
            refreshed_access_token = refreshed_payload[ACCESS_TOKEN_FIELD]
            refreshed_refresh_token = refreshed_payload[REFRESH_TOKEN_FIELD]
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
            assert refresh_response.status_code == 200
            assert reused_response.status_code == 401
            assert (
                reused_response.json()[DATA_FIELD][ERROR_CODE_FIELD] == AuthErrorCode.TOKEN_REUSED
            )
            assert revoked_access_response.status_code == 401
            assert (
                revoked_access_response.json()[DATA_FIELD][ERROR_CODE_FIELD]
                == AuthErrorCode.TOKEN_REVOKED
            )
            assert revoked_refresh_response.status_code == 401
            assert (
                revoked_refresh_response.json()[DATA_FIELD][ERROR_CODE_FIELD]
                == AuthErrorCode.TOKEN_REVOKED
            )

    def test_auth_me_when_token_scope_snapshot_outdated_should_follow_database_truth(
        self,
    ) -> None:
        """
        验证鉴权当前主体当令牌作用域快照过期应遵循数据库真实状态。

        :returns: 无返回值。
        :rtype: None
        """

        app = TestAppFactory().create()
        with TestClient(app) as client:
            token_response = client.post(
                "/auth/token",
                json={"username": "admin", "password": "admin"},
            )
            refresh_token = token_response.json()["data"]["refresh_token"]
            token_payload = app.state.container.resource_mount.get_jwt_token_service().decode_token(
                refresh_token,
                expected_use=TokenUse.REFRESH,
            )
            access_token = (
                app.state.container.resource_mount.get_jwt_token_service()
                .issue_token_pair(
                    AuthenticatedPrincipal(
                        subject_id="user-admin",
                        username="admin",
                        roles=[AuthRoleKey.ADMIN],
                        scopes=[AuthScopeCode.SYSTEM_READ],
                    ),
                    token_session_id=token_payload.token_session_id,
                )
                .response_payload.access_token
            )
            response = client.get(
                "/auth/me",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            assert response.status_code == 200
            assert response.json()["data"]["subject_id"] == "user-admin"
            assert "auth:read" in response.json()["data"]["scopes"]

    def test_password_rehash_when_needed_should_persist_new_hash(
        self,
        monkeypatch,
    ) -> None:
        """
        验证鉴权令牌当密码哈希需要重算哈希应持久化新哈希。

        :param monkeypatch: 当前步骤使用的monkeypatch参数。
        :type monkeypatch: Any
        :returns: 无返回值。
        :rtype: None
        :raises AssertionError: 当当前步骤检测到异常条件时抛出。
        """

        app = TestAppFactory().create()
        with TestClient(app):
            resource_mount = app.state.container.resource_mount
            unit_of_work = resource_mount.create_unit_of_work()
            try:
                repository = resource_mount.create_auth_identity_repository(
                    unit_of_work.get_session()
                )
                auth_identity = repository.get_by_username("admin")
                if auth_identity is None:
                    raise AssertionError("引导管理员未创建。")
                original_password_hash = auth_identity.password_hash
                original_user_id = auth_identity.user_id
            finally:
                unit_of_work.dispose()

            monkeypatch.setattr(
                PasswordHasher,
                "needs_rehash",
                lambda _self, _password_hash: True,
            )
            monkeypatch.setattr(
                PasswordHasher,
                "hash_password",
                lambda _self, _password_plain: "rehash-password-hash",
            )

            try:
                app.state.container.issue_access_token_usecase.execute(
                    CredentialInput(username="admin", password_plain="admin")
                )

                verify_unit_of_work = resource_mount.create_unit_of_work()
                try:
                    repository = resource_mount.create_auth_identity_repository(
                        verify_unit_of_work.get_session()
                    )
                    auth_identity = repository.get_by_username("admin")
                    if auth_identity is None:
                        raise AssertionError("引导管理员未创建。")
                    assert auth_identity.password_hash == "rehash-password-hash"
                finally:
                    verify_unit_of_work.dispose()
            finally:
                restore_unit_of_work = resource_mount.create_unit_of_work()
                try:
                    repository = resource_mount.create_auth_identity_repository(
                        restore_unit_of_work.get_session()
                    )
                    repository.update_password_hash(
                        user_id=original_user_id,
                        password_hash=original_password_hash,
                    )
                    restore_unit_of_work.commit()
                finally:
                    restore_unit_of_work.dispose()

    def _reload_runtime_limit(
        self,
        *,
        coordinator: SettingsReloadCoordinator,
        start_barrier: Barrier,
    ) -> ReloadResultPayload:
        """
        并发触发运行时热更新。
        """

        start_barrier.wait(timeout=CONCURRENT_RUNTIME_TIMEOUT_SECONDS)
        return coordinator.reload_from_mapping(
            environment=AppEnvironment.TEST,
            overrides={
                "runtime": {"web": {"max_request_body_bytes": CONCURRENT_RUNTIME_RELOAD_BODY_LIMIT}}
            },
        )

    def _dispatch_default_task(
        self,
        *,
        app: FastAPI,
        start_barrier: Barrier,
    ) -> TaskDispatchResultPayload:
        """
        并发分发默认任务。
        """

        start_barrier.wait(timeout=CONCURRENT_RUNTIME_TIMEOUT_SECONDS)
        return app.state.container.dispatch_background_job_usecase.execute(
            TaskDispatchCommand(payload=DemoTaskPayload())
        )

    def _read_runtime_bundle_consistency(
        self,
        *,
        resource_mount: SharedResourceMount,
        start_barrier: Barrier,
    ) -> bool:
        """
        并发读取运行时公开入口并验证后端快照一致。
        """

        start_barrier.wait(timeout=CONCURRENT_RUNTIME_TIMEOUT_SECONDS)
        registration_snapshots = resource_mount.list_task_registration_snapshots()
        current_runtime_backends = {
            snapshot.current_runtime_backend for snapshot in registration_snapshots
        }
        return (
            len(current_runtime_backends) == EXPECTED_SINGLE_RUNTIME_BACKEND_COUNT
            and resource_mount.get_current_task_backend() in current_runtime_backends
            and resource_mount.get_task_dispatcher() is not None
        )
