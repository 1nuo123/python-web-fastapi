"""
Web 执行路径测试模块。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from src.api.asgi_entry import create_app
from src.api.testing.test_app_factory import TestAppFactory
from src.infrastructure.settings.application_settings import AppEnvironment
from src.infrastructure.testing.sqlite_test_engine_factory import SqliteTestEngineFactory

AUTH_TOKEN_PATH = "/auth/token"
ADMIN_ROLES_PATH = "/admin/roles"
AUTHORIZATION_HEADER = "Authorization"
BEARER_PREFIX = "Bearer"


class TestWebExecutionPath:
    """
    Web 执行路径测试集合。
    """

    def test_asgi_entry_should_start_lifespan_and_expose_health_live(self) -> None:
        """
        验证真实 ASGI 入口不依赖测试任务绑定也能启动。
        """

        app = create_app(
            environment=AppEnvironment.TEST,
            database_engine_factory=SqliteTestEngineFactory(),
        )

        with TestClient(app) as client:
            health_response = client.get("/health/live")

        assert health_response.status_code == 200
        assert health_response.json()["data"]["status"] == "alive"

    def test_routes_when_threadpool_execution_enabled_should_keep_sync_backbone(
        self,
    ) -> None:
        """
        验证 Web 路由在线程池执行策略下应保持同步主干。
        """

        app = TestAppFactory().create()

        with TestClient(app) as client:
            health_response = client.get("/health/live")
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

        assert health_response.status_code == 200
        assert health_response.json()["data"]["status"] == "alive"
        assert role_response.status_code == 200

    def test_resource_mount_when_async_http_mode_enabled_should_expose_async_client(
        self,
    ) -> None:
        """
        验证资源挂载点当异步 HTTP 模式启用应暴露异步客户端。
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
            async_http_client = app.state.container.resource_mount.get_async_http_client()
            sync_http_client = app.state.container.resource_mount.get_http_client()
            assert async_http_client.get_client().is_closed is False
            assert sync_http_client.get_client().is_closed is False
