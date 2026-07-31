"""统一流式运行时初始化测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from src.api.admin_task_stream_binding_factory import (
    ADMIN_TASK_STREAM_BATCH_SUFFIX,
    ADMIN_TASK_STREAM_SSE_SUFFIX,
    ADMIN_TASK_STREAM_WEBSOCKET_SUFFIX,
)
from src.api.testing.test_app_factory import TestAppFactory
from src.cli.run_web_server import WebServerRuntimeProjection
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.stream_contract.stream_runtime_contract import RedisStreamRuntimeDetail
from src.infrastructure.settings.app_settings_loader import AppSettingsLoader
from src.infrastructure.settings.application_settings import AppEnvironment

COMPOSE_STOP_GRACE_SECONDS = 40
STREAM_HOT_RELOAD_PATHS = {
    "runtime.stream.detail.send_timeout_seconds",
    "runtime.stream.detail.sse_heartbeat_seconds",
    "runtime.stream.detail.sse_retry_milliseconds",
}
STREAM_COMMON_FIELD_PATHS = {
    "runtime.stream",
    "runtime.stream.envelope_kind",
    "runtime.stream.schema_version",
    "runtime.stream.header.kind",
    "runtime.stream.header.schema_version",
    "runtime.stream.header.mode",
    "runtime.stream.header.enabled",
    "runtime.stream.detail.kind",
    "runtime.stream.detail.schema_version",
    "runtime.stream.detail.queue_capacity",
    "runtime.stream.detail.send_timeout_seconds",
    "runtime.stream.detail.max_duration_seconds",
    "runtime.stream.detail.max_event_bytes",
    "runtime.stream.detail.collection_max_events",
    "runtime.stream.detail.collection_max_bytes",
    "runtime.stream.detail.collection_timeout_seconds",
    "runtime.stream.detail.max_sessions",
    "runtime.stream.detail.max_sessions_per_subject",
    "runtime.stream.detail.max_sessions_per_ip",
    "runtime.stream.detail.max_sessions_per_operation",
    "runtime.stream.detail.ticket_ttl_seconds",
    "runtime.stream.detail.replay_ttl_seconds",
    "runtime.stream.detail.replay_max_events",
    "runtime.stream.detail.sse_heartbeat_seconds",
    "runtime.stream.detail.sse_retry_milliseconds",
    "runtime.stream.detail.websocket_max_message_bytes",
    "runtime.stream.detail.websocket_ping_interval_seconds",
    "runtime.stream.detail.websocket_ping_timeout_seconds",
    "runtime.stream.detail.shutdown_grace_seconds",
    "runtime.stream.detail.allowed_origins",
    "runtime.stream.detail.require_browser_ticket",
}
STREAM_REDIS_FIELD_PATHS = {
    "runtime.stream.detail.redis_url",
    "runtime.stream.detail.redis_key_prefix",
    "runtime.stream.detail.redis_socket_connect_timeout_seconds",
    "runtime.stream.detail.redis_max_connections",
}


class TestStreamingRuntimeInitialization:
    """统一流式运行时初始化测试集合。"""

    def test_test_environment_should_load_small_local_runtime(self) -> None:
        """验证测试环境加载小配额本地流运行时。"""

        runtime = AppSettingsLoader().load_for_environment(AppEnvironment.TEST).runtime.stream

        assert runtime.header.enabled is True
        assert runtime.detail.queue_capacity == 4
        assert runtime.detail.shutdown_grace_seconds == 1.0

    def test_production_when_stream_origin_wildcard_should_reject(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """验证生产流式 Origin 通配符被安全校验拒绝。"""

        self._set_production_environment(monkeypatch)
        with pytest.raises(HttpFaultException):
            AppSettingsLoader().load_from_mapping(
                environment=AppEnvironment.PRODUCTION,
                overrides={
                    "runtime": {
                        "stream": {
                            "detail": {"allowed_origins": ["*"]},
                        }
                    }
                },
            )

    def test_lifespan_should_start_and_release_stream_resources(self) -> None:
        """验证 lifespan 内启动并在退出时释放流资源。"""

        app = TestAppFactory().create()
        resource_mount = app.state.container.resource_mount
        with TestClient(app):
            resources = resource_mount.get_streaming_resources()
            assert resources.session_registry.active_count() == 0
        with pytest.raises(Exception):
            resource_mount.get_streaming_resources()

    def test_production_should_use_redis_stream_runtime(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """验证生产环境冻结 Redis 流状态后端。"""

        self._set_production_environment(monkeypatch)
        runtime = AppSettingsLoader().load_for_environment(AppEnvironment.PRODUCTION).runtime.stream

        assert isinstance(runtime.detail, RedisStreamRuntimeDetail)

    @pytest.mark.parametrize(
        ("field_name", "value"),
        [
            ("max_sessions", 100001),
            ("max_event_bytes", 10485761),
            ("max_duration_seconds", 86401.0),
            ("ticket_ttl_seconds", 86401),
            ("replay_ttl_seconds", 86401),
            ("redis_max_connections", 10001),
        ],
    )
    def test_production_when_stream_limit_exceeds_safety_bound_should_reject(
        self,
        monkeypatch: pytest.MonkeyPatch,
        field_name: str,
        value: int | float,
    ) -> None:
        """验证生产流式配额、字节、持续时间、TTL 与连接池安全上界。"""

        self._set_production_environment(monkeypatch)
        with pytest.raises(HttpFaultException):
            AppSettingsLoader().load_from_mapping(
                environment=AppEnvironment.PRODUCTION,
                overrides={"runtime": {"stream": {"detail": {field_name: value}}}},
            )

    def test_web_server_projection_and_compose_should_exceed_application_drain(self) -> None:
        """冻结应用排空、Uvicorn 和 Compose 停机窗口的严格大小关系。"""

        runtime = AppSettingsLoader().load_for_environment(AppEnvironment.TEST).runtime.stream
        projection = WebServerRuntimeProjection.from_stream_runtime(runtime.detail)
        compose_document = yaml.safe_load(Path("compose.yml").read_text(encoding="utf-8"))
        stop_grace = compose_document["services"]["app"]["stop_grace_period"]

        assert projection.graceful_shutdown_seconds > runtime.detail.shutdown_grace_seconds
        assert stop_grace == f"{COMPOSE_STOP_GRACE_SECONDS}s"
        assert COMPOSE_STOP_GRACE_SECONDS > projection.graceful_shutdown_seconds

    def test_every_stream_runtime_field_should_have_restart_or_hot_classification(self) -> None:
        """验证每个流运行时字段均被明确分类且两类不重叠。"""

        settings = AppSettingsLoader().load_for_environment(AppEnvironment.TEST)
        hot_paths = set(settings.app.reload.hot_reload_allowed)
        restart_paths = set(settings.app.reload.restart_required)
        expected_paths = STREAM_COMMON_FIELD_PATHS | STREAM_REDIS_FIELD_PATHS

        assert STREAM_HOT_RELOAD_PATHS <= hot_paths
        assert STREAM_HOT_RELOAD_PATHS.isdisjoint(restart_paths)
        assert expected_paths <= hot_paths | restart_paths

    def test_admin_task_module_should_register_production_three_transport_binding(self) -> None:
        """验证生产业务绑定复用共享资源集并登记三种交付路径。"""

        app = TestAppFactory().create(overrides={"app": {"modules": {"enabled": ["admin_task"]}}})
        api_prefix = app.state.container.settings_holder.current_settings.runtime.web.api_prefix
        paths = {getattr(route, "path", "") for route in app.routes}
        with TestClient(app):
            resources = app.state.container.resource_mount.get_streaming_resources()
            assert len(resources.operation_components) == 1

        assert f"{api_prefix}{ADMIN_TASK_STREAM_BATCH_SUFFIX}" in paths
        assert f"{api_prefix}{ADMIN_TASK_STREAM_SSE_SUFFIX}" in paths
        assert f"{api_prefix}{ADMIN_TASK_STREAM_WEBSOCKET_SUFFIX}" in paths

    def _set_production_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """设置生产配置加载所需外部敏感变量。"""

        monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@db:5432/app")
        monkeypatch.setenv("REDIS_URL", "redis://:password@redis:6379/0")
        monkeypatch.setenv("RABBITMQ_URL", "amqp://u:p@rabbitmq:5672/%2F")
        monkeypatch.setenv("JWT_SECRET", "production-random-secret-value-2026-xyz")
