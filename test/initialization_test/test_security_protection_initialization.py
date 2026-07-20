"""
安全防护初始化测试模块。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from src.api.testing.test_app_factory import TestAppFactory
from src.infrastructure.settings.app_settings_loader import AppSettingsLoader
from src.infrastructure.settings.application_settings import AppEnvironment

AUTH_TOKEN_POLICY_NAME = "auth_token"
ASYNC_HTTP_MODE = "async_http"
OUTBOUND_HTTP_CLIENT_ENVELOPE_KIND = "outbound_http_client_envelope"
OUTBOUND_HTTP_CLIENT_HEADER_KIND = "outbound_http_client_header"
OUTBOUND_HTTP_CLIENT_NAME = "default_outbound_http"
OUTBOUND_HTTP_CLIENT_SCHEMA_VERSION = "1.0"
ASYNC_HTTP_TIMEOUT_SECONDS = 5
ASYNC_HTTP_MAX_CONNECTIONS = 20
ASYNC_HTTP_MAX_KEEPALIVE_CONNECTIONS = 10
RELOAD_HTTP_TIMEOUT_SECONDS = 6
MINIMUM_INSTALLED_HOOK_COUNT = 1


class TestSecurityProtectionInitialization:
    """
    安全防护初始化测试集合。
    """

    def test_settings_should_load_security_lock_and_key_management_runtime(self) -> None:
        """
        验证安全、锁、密钥管理运行时可完成配置加载。
        """

        settings = AppSettingsLoader("config").load_for_environment(AppEnvironment.TEST)

        assert settings.runtime.security.detail.protection.flow_control.enabled is True
        assert settings.runtime.distributed_lock.header.enabled is True
        assert settings.runtime.key_management.header.enabled is True
        assert (
            settings.runtime.security.detail.protection.flow_control.policies[0].header.policy_name
            == AUTH_TOKEN_POLICY_NAME
        )

    def test_shared_resource_mount_should_install_sync_http_ssrf_hook(self) -> None:
        """
        验证共享资源挂载后同步 HTTP 客户端安装 SSRF 钩子。
        """

        app = TestAppFactory().create()

        with TestClient(app):
            hooks = (
                app.state.container.resource_mount.get_http_client()
                .get_client()
                .event_hooks["request"]
            )

        assert len(hooks) >= 1

    def test_shared_resource_mount_should_install_async_http_ssrf_hook(self) -> None:
        """
        验证异步共享 HTTP 客户端启动后安装 SSRF 钩子。
        """

        app = TestAppFactory().create(overrides=self._build_async_http_overrides())

        with TestClient(app):
            sync_hooks = (
                app.state.container.resource_mount.get_http_client()
                .get_client()
                .event_hooks["request"]
            )
            async_hooks = (
                app.state.container.resource_mount.get_async_http_client()
                .get_client()
                .event_hooks["request"]
            )

        assert len(sync_hooks) >= MINIMUM_INSTALLED_HOOK_COUNT
        assert len(async_hooks) >= MINIMUM_INSTALLED_HOOK_COUNT

    def test_apply_settings_should_reinstall_ssrf_hook_after_http_resource_switch(
        self,
    ) -> None:
        """
        验证热切换 HTTP 资源后重新安装 SSRF 钩子。
        """

        app = TestAppFactory().create()

        with TestClient(app):
            candidate_settings = AppSettingsLoader("config").load_from_mapping(
                environment=AppEnvironment.TEST,
                overrides={
                    "runtime": {
                        "web": {
                            "outbound_http_client": {
                                "detail": {"timeout_seconds": RELOAD_HTTP_TIMEOUT_SECONDS}
                            }
                        }
                    }
                },
            )
            result = app.state.container.resource_mount.apply_settings(candidate_settings)
            hooks = (
                app.state.container.resource_mount.get_http_client()
                .get_client()
                .event_hooks["request"]
            )

        assert result.success is True
        assert len(hooks) >= MINIMUM_INSTALLED_HOOK_COUNT

    def _build_async_http_overrides(self) -> dict[str, object]:
        """
        构建异步 HTTP 客户端覆盖配置。
        """

        return {
            "runtime": {
                "web": {
                    "outbound_http_client": {
                        "envelope_kind": OUTBOUND_HTTP_CLIENT_ENVELOPE_KIND,
                        "schema_version": OUTBOUND_HTTP_CLIENT_SCHEMA_VERSION,
                        "header": {
                            "kind": OUTBOUND_HTTP_CLIENT_HEADER_KIND,
                            "schema_version": OUTBOUND_HTTP_CLIENT_SCHEMA_VERSION,
                            "client_name": OUTBOUND_HTTP_CLIENT_NAME,
                            "enabled": True,
                            "mode": ASYNC_HTTP_MODE,
                        },
                        "detail": {
                            "kind": ASYNC_HTTP_MODE,
                            "schema_version": OUTBOUND_HTTP_CLIENT_SCHEMA_VERSION,
                            "timeout_seconds": ASYNC_HTTP_TIMEOUT_SECONDS,
                            "max_connections": ASYNC_HTTP_MAX_CONNECTIONS,
                            "max_keepalive_connections": ASYNC_HTTP_MAX_KEEPALIVE_CONNECTIONS,
                        },
                    }
                }
            }
        }
