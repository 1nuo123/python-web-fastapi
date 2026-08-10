"""
测试应用集成测试模块。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict

from src.api.testing.test_app_factory import TestAppFactory
from src.api.web_bundle_catalog import ENABLED_MODULES_CONFIG_PATH, WebBundleCatalog
from src.application.dispatch_background_job_usecase import TaskDispatchCommand
from src.core.http_contract.web_bundle_contract import ApplicationModuleName
from src.core.task_contract.task_handler_contract import TaskHandler
from src.core.task_contract.task_invocation_contract import TypedTaskInvocation
from src.infrastructure.task.task_registration_registry import RegisteredTaskBinding

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.usefixtures("integration_database"),
]


API_PREFIX = "/api/v1"
AUTH_ME_PATH = "/auth/me"
AUTH_REFRESH_PATH = "/auth/refresh"
AUTH_REVOKE_PATH = "/auth/revoke"
AUTH_TOKEN_PATH = "/auth/token"
HEALTH_LIVE_PATH = "/health/live"
ADMIN_ROLES_PATH = "/admin/roles"
SYSTEM_INFO_PATH = "/system/info"
AUTHORIZATION_HEADER = "Authorization"
BEARER_PREFIX = "Bearer"
UNKNOWN_WEB_MODULE_NAME = "unknown_module"
CONCURRENT_RELOAD_BODY_LIMITS = (4096, 8192)
CONCURRENT_RELOAD_WORKER_COUNT = 2


class DemoTaskPayload(BaseModel):
    """
    示例任务Pydantic 模型，用于承载并校验结构化数据。

    :ivar model_config: Pydantic 模型配置对象。约束：需满足当前实现中的类型与状态约束。默认值：`ConfigDict(extra='forbid')`。取值语义：用于控制 Pydantic 模型的额外字段和校验行为。
    :vartype model_config: ConfigDict
    :ivar kind: 结构版本的具体类型标识。约束：需符合 ``str`` 注解。默认值：`'demo_task'`。取值语义：用于承载当前对象中的业务状态。
    :vartype kind: str
    :ivar schema_version: 结构模式版本。约束：需符合 ``str`` 注解。默认值：`'1.0'`。取值语义：用于承载当前对象中的业务状态。
    :vartype schema_version: str
    :ivar task_id: ``task_id`` 字段。约束：需符合 ``str`` 注解。默认值：`'integration-task'`。取值语义：用于唯一标识对应实体。
    :vartype task_id: str
    """

    model_config = ConfigDict(extra="forbid")

    kind: str = "demo_task"
    schema_version: str = "1.0"
    task_id: str = "integration-task"


class DemoTaskHandler(TaskHandler[DemoTaskPayload]):
    """
    示例任务处理器。
    """

    def handle(self, invocation: TypedTaskInvocation[DemoTaskPayload]) -> None:
        _ = invocation
        return None


class TestAppIntegration:
    """
    测试应用集成测试集合，用于组织同一主题下的测试场景。
    """

    def test_app_startup_should_connect_system_and_auth_chain(self) -> None:
        """
        验证应用启动应连接系统与鉴权链路。

        :returns: 无返回值。
        :rtype: None
        """

        app = TestAppFactory().create(
            task_bindings=[
                RegisteredTaskBinding(
                    job_kind="demo_task",
                    payload_model=DemoTaskPayload,
                    handler=DemoTaskHandler(),
                )
            ]
        )
        with TestClient(app) as client:
            health_response = client.get(HEALTH_LIVE_PATH)
            token_response = client.post(
                AUTH_TOKEN_PATH,
                json={"username": "admin", "password": "admin"},
            )
            role_response = client.get(
                ADMIN_ROLES_PATH,
                headers={
                    AUTHORIZATION_HEADER: (
                        f"{BEARER_PREFIX} {token_response.json()['data']['access_token']}"
                    )
                },
            )
            refresh_response = client.post(
                AUTH_REFRESH_PATH,
                json={"refresh_token": token_response.json()["data"]["refresh_token"]},
            )
            me_response = client.get(
                AUTH_ME_PATH,
                headers={
                    "Authorization": (f"Bearer {refresh_response.json()['data']['access_token']}")
                },
            )
            dispatch_result = app.state.container.dispatch_background_job_usecase.execute(
                TaskDispatchCommand(payload=DemoTaskPayload())
            )
            assert health_response.status_code == 200
            assert "X-Request-ID" in health_response.headers
            assert role_response.status_code == 200
            assert token_response.status_code == 200
            assert refresh_response.status_code == 200
            assert me_response.status_code == 200
            assert dispatch_result.dispatched is True
            assert dispatch_result.backend.value == "local"
            assert dispatch_result.queue_name == "demo_task"

    def test_app_startup_should_prepare_request_execution_bridge_for_async_routes(
        self,
    ) -> None:
        """
        验证应用启动应为异步路由准备请求执行桥接器。
        """

        app = TestAppFactory().create()

        with TestClient(app) as client:
            resource_mount = client.app.state.container.resource_mount
            health_response = client.get(HEALTH_LIVE_PATH)
            access_token = self._issue_admin_access_token(client)
            role_response = client.get(
                ADMIN_ROLES_PATH,
                headers={AUTHORIZATION_HEADER: f"{BEARER_PREFIX} {access_token}"},
            )

            assert resource_mount.get_request_execution_bridge() is not None
            assert health_response.status_code == 200
            assert role_response.status_code == 200

    def test_revoked_session_should_invalidate_old_access_token(self) -> None:
        """
        验证已撤销会话应失效旧访问令牌。

        :returns: 无返回值。
        :rtype: None
        """

        app = TestAppFactory().create()
        with TestClient(app) as client:
            token_response = client.post(
                AUTH_TOKEN_PATH,
                json={"username": "admin", "password": "admin"},
            )
            access_token = token_response.json()["data"]["access_token"]
            refresh_token = token_response.json()["data"]["refresh_token"]
            revoke_response = client.post(
                AUTH_REVOKE_PATH,
                json={"refresh_token": refresh_token},
            )
            me_response = client.get(
                AUTH_ME_PATH,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            assert revoke_response.status_code == 200
            assert me_response.status_code == 401
            assert me_response.json()["data"]["error_code"] == "auth.token.revoked"

    def test_app_when_auth_module_disabled_should_not_mount_auth_routes(self) -> None:
        """
        验证应用当鉴权模块禁用应不挂载点鉴权路由集合。

        :returns: 无返回值。
        :rtype: None
        """

        app = TestAppFactory().create(
            overrides={
                "app": {
                    "modules": {
                        "enabled": ["health_probe", "system_overview"],
                    }
                }
            }
        )
        with TestClient(app) as client:
            token_response = client.post(
                AUTH_TOKEN_PATH,
                json={"username": "admin", "password": "admin"},
            )
            overview_response = client.get(SYSTEM_INFO_PATH)
            assert overview_response.status_code == 401
            assert token_response.status_code == 404

    def test_app_when_enabled_modules_contains_unknown_should_fail_startup(self) -> None:
        """
        验证应用当启用模块包含未知值应启动失败。
        """

        with pytest.raises(ValueError) as fault:
            TestAppFactory().create(
                overrides={
                    "app": {
                        "modules": {
                            "enabled": ["health_probe", UNKNOWN_WEB_MODULE_NAME],
                        }
                    }
                }
            )

        error_message = str(fault.value)
        assert ENABLED_MODULES_CONFIG_PATH in error_message
        assert UNKNOWN_WEB_MODULE_NAME in error_message

    def test_app_when_api_prefix_configured_should_mount_prefixed_routes_and_openapi_paths(
        self,
    ) -> None:
        """
        验证应用当API前缀已配置应挂载点带前缀路由集合与OpenAPI路径集合。

        :returns: 无返回值。
        :rtype: None
        """

        app = TestAppFactory().create(overrides={"runtime": {"web": {"api_prefix": API_PREFIX}}})
        with TestClient(app) as client:
            legacy_response = client.get(HEALTH_LIVE_PATH)
            prefixed_health_response = client.get(f"{API_PREFIX}{HEALTH_LIVE_PATH}")
            prefixed_token_response = client.post(
                f"{API_PREFIX}{AUTH_TOKEN_PATH}",
                json={"username": "admin", "password": "admin"},
            )
            prefixed_role_response = client.get(
                f"{API_PREFIX}{ADMIN_ROLES_PATH}",
                headers={
                    AUTHORIZATION_HEADER: (
                        f"{BEARER_PREFIX} {prefixed_token_response.json()['data']['access_token']}"
                    )
                },
            )
            openapi_document = app.openapi()
            assert legacy_response.status_code == 404
            assert prefixed_health_response.status_code == 200
            assert prefixed_role_response.status_code == 200
            assert prefixed_token_response.status_code == 200
            assert f"{API_PREFIX}{HEALTH_LIVE_PATH}" in openapi_document["paths"]
            assert f"{API_PREFIX}{SYSTEM_INFO_PATH}" not in openapi_document["paths"]
            assert f"{API_PREFIX}{ADMIN_ROLES_PATH}" in openapi_document["paths"]
            assert f"{API_PREFIX}{AUTH_TOKEN_PATH}" in openapi_document["paths"]

    def test_app_when_reload_runtime_limit_should_keep_provider_routing_and_snapshot(self) -> None:
        """
        验证应用热更新后应保持 provider 装配与快照结果。
        """

        app = TestAppFactory().create()
        with TestClient(app) as client:
            coordinator = app.state.container.reload_coordinator
            result = coordinator.reload_from_mapping(
                environment=(app.state.container.settings_holder.current_settings.app.environment),
                overrides={"runtime": {"web": {"max_request_body_bytes": 4096}}},
            )
            response = client.get(HEALTH_LIVE_PATH)
            provider_modules = [
                envelope.header.module_name
                for envelope in WebBundleCatalog().list_provider_envelopes()
            ]

            assert result.success is True
            assert result.rolled_back is False
            assert result.active_snapshot_id is not None
            assert response.status_code == 200
            assert sorted(provider_modules) == sorted(
                [
                    ApplicationModuleName.HEALTH_PROBE.value,
                    ApplicationModuleName.SYSTEM_OVERVIEW.value,
                    ApplicationModuleName.AUTH_ACCESS.value,
                    ApplicationModuleName.SECURITY_PROTECTION.value,
                    ApplicationModuleName.ADMIN_TASK.value,
                    ApplicationModuleName.ADMIN_SETTINGS.value,
                    ApplicationModuleName.ADMIN_LOG.value,
                    ApplicationModuleName.ADMIN_IDENTITY.value,
                    ApplicationModuleName.ADMIN_AUDIT.value,
                    ApplicationModuleName.CODEX_CONTROL.value,
                    ApplicationModuleName.CODEX_AGENT_GATEWAY.value,
                ]
            )

    def test_app_when_reload_concurrently_should_swap_runtime_atomically(self) -> None:
        """验证并发热更新串行切换不可变运行时包且不丢失代际。"""

        app = TestAppFactory().create()
        with TestClient(app):
            container = app.state.container
            coordinator = container.reload_coordinator
            resource_mount = container.resource_mount
            environment = container.settings_holder.current_settings.app.environment
            initial_generation = resource_mount.read_runtime_bundle().generation

            with ThreadPoolExecutor(max_workers=CONCURRENT_RELOAD_WORKER_COUNT) as executor:
                futures = [
                    executor.submit(
                        coordinator.reload_from_mapping,
                        environment=environment,
                        overrides={"runtime": {"web": {"max_request_body_bytes": body_limit}}},
                    )
                    for body_limit in CONCURRENT_RELOAD_BODY_LIMITS
                ]
                results = [future.result() for future in futures]

            final_bundle = resource_mount.read_runtime_bundle()

            assert all(result.success for result in results)
            assert all(result.rolled_back is False for result in results)
            assert final_bundle.generation == initial_generation + len(results)
            assert (
                final_bundle.settings.runtime.web.max_request_body_bytes
                in CONCURRENT_RELOAD_BODY_LIMITS
            )

    def _issue_admin_access_token(self, client: TestClient) -> str:
        """
        签发管理员访问令牌。
        """

        token_response = client.post(
            AUTH_TOKEN_PATH,
            json={"username": "admin", "password": "admin"},
        )
        return str(token_response.json()["data"]["access_token"])
