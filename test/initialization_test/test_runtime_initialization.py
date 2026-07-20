"""
运行时初始化测试模块。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from src.api.testing.test_app_factory import TestAppFactory
from src.core.http_contract.runtime_resource_contract import RuntimeResourceStatus
from src.infrastructure.resource_mount.shared_resource_constants import (
    RESOURCE_ASYNC_HTTP_CLIENT,
    RESOURCE_CACHE,
    RESOURCE_DATABASE,
    RESOURCE_DISTRIBUTED_LOCK,
    RESOURCE_HTTP_CLIENT,
    RESOURCE_KEY_MANAGEMENT,
    RESOURCE_LOGGING,
    RESOURCE_TASK,
    RESOURCE_TASK_MESSAGE_TRANSPORT,
)


class TestRuntimeInitialization:
    """
    运行时初始化测试集合。
    """

    def test_startup_should_prepare_request_execution_bridge_and_sync_http_client(
        self,
    ) -> None:
        """
        验证启动应准备请求执行桥接器与同步 HTTP 客户端。
        """

        app = TestAppFactory().create()

        with TestClient(app):
            resource_mount = app.state.container.resource_mount
            states = {state.resource_name: state for state in resource_mount.get_runtime_states()}
            assert resource_mount.get_request_execution_bridge() is not None
            assert resource_mount.get_http_client() is not None
            assert states[RESOURCE_HTTP_CLIENT].status == RuntimeResourceStatus.READY
            assert states[RESOURCE_ASYNC_HTTP_CLIENT].status == RuntimeResourceStatus.STOPPED
            assert states[RESOURCE_DATABASE].status == RuntimeResourceStatus.READY
            assert states[RESOURCE_LOGGING].status == RuntimeResourceStatus.READY
            assert states[RESOURCE_CACHE].status == RuntimeResourceStatus.READY
            assert states[RESOURCE_DISTRIBUTED_LOCK].status == RuntimeResourceStatus.READY
            assert states[RESOURCE_KEY_MANAGEMENT].status == RuntimeResourceStatus.READY
            assert states[RESOURCE_TASK_MESSAGE_TRANSPORT].status == RuntimeResourceStatus.READY
            assert states[RESOURCE_TASK].status == RuntimeResourceStatus.READY

    def test_startup_should_mount_distributed_lock_runtime_settings(self) -> None:
        """
        验证分布式锁运行时配置会装配到锁 Provider 与密钥轮转锁。
        """

        app = TestAppFactory().create()

        with TestClient(app):
            resource_mount = app.state.container.resource_mount
            settings = app.state.container.settings_holder.current_settings
            provider = resource_mount.get_distributed_lock_provider()
            key_management_service = resource_mount.get_key_management_service()

            assert provider._enabled is settings.runtime.distributed_lock.header.enabled  # noqa: SLF001
            assert (  # noqa: SLF001
                key_management_service._rotation_lock_lease_seconds
                == settings.runtime.distributed_lock.detail.lease_seconds
            )
            assert (  # noqa: SLF001
                key_management_service._rotation_lock_wait_seconds
                == settings.runtime.distributed_lock.detail.wait_seconds
            )

    def test_startup_when_async_http_mode_enabled_should_prepare_async_http_client(
        self,
    ) -> None:
        """
        验证启动当异步 HTTP 模式启用应准备异步 HTTP 客户端。
        """

        app = TestAppFactory().create(
            overrides={
                "runtime": {
                    "web": {
                        "outbound_http_client": {
                            "envelope_kind": "outbound_http_client_envelope",
                            "schema_version": "1.0",
                            "header": {
                                "kind": "outbound_http_client_header",
                                "schema_version": "1.0",
                                "client_name": "default_outbound_http",
                                "enabled": True,
                                "mode": "async_http",
                            },
                            "detail": {
                                "kind": "async_http",
                                "schema_version": "1.0",
                                "timeout_seconds": 5,
                                "max_connections": 10,
                                "max_keepalive_connections": 5,
                            },
                        }
                    }
                }
            }
        )

        with TestClient(app):
            resource_mount = app.state.container.resource_mount
            states = {state.resource_name: state for state in resource_mount.get_runtime_states()}
            assert resource_mount.get_async_http_client() is not None
            assert states[RESOURCE_ASYNC_HTTP_CLIENT].status == RuntimeResourceStatus.READY
