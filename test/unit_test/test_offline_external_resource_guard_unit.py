"""离线外部资源逐项授权单元测试。"""

from __future__ import annotations

import socket
from typing import cast

import pytest

from test.conftest import (
    OFFLINE_CONNECTION_BLOCKED_MESSAGE,
    ExternalResourceMarker,
    OfflineExternalResourceGuard,
)

REDIS_TEST_ADDRESS = ("127.0.0.1", 6379)
CONFIGURED_REDIS_TEST_ADDRESS = ("127.0.0.1", 56380)
CONFIGURED_POSTGRES_TEST_ADDRESS = ("127.0.0.1", 55433)
RABBITMQ_TEST_ADDRESS = ("127.0.0.1", 5672)
POSTGRES_TEST_ARGUMENT = "postgresql://test"
PUBLIC_NETWORK_ADDRESS = ("198.51.100.10", 443)
DOCKER_COMMAND = ("docker", "compose", "ps")
DOCKER_NAMED_PIPE = r"\\.\pipe\docker_engine"


class StubExternalConnectCallable:
    """记录外部连接调用且不建立真实连接。"""

    def __init__(self) -> None:
        """初始化调用次数。"""

        self.call_count = 0

    def __call__(self, *args: object, **kwargs: object) -> object:
        """记录调用并返回稳定占位对象。"""

        _ = args, kwargs
        self.call_count += 1
        return self


class TestOfflineExternalResourceGuardUnit:
    """验证 marker 只授权对应外部资源。"""

    def test_postgres_connection_without_postgres_marker_should_reject(self) -> None:
        """验证未声明 PostgreSQL 时拒绝数据库连接。"""

        guard, postgres_connect = self._build_guard(frozenset())

        with pytest.raises(RuntimeError, match=OFFLINE_CONNECTION_BLOCKED_MESSAGE):
            guard.connect_postgres(POSTGRES_TEST_ARGUMENT)

        assert postgres_connect.call_count == 0

    def test_postgres_connection_with_postgres_marker_should_allow(self) -> None:
        """验证 PostgreSQL marker 只放行数据库连接入口。"""

        guard, postgres_connect = self._build_guard(frozenset({ExternalResourceMarker.POSTGRES}))

        result = guard.connect_postgres(POSTGRES_TEST_ARGUMENT)

        assert result is postgres_connect
        assert postgres_connect.call_count == 1

    def test_redis_marker_when_connecting_rabbitmq_port_should_reject(self) -> None:
        """验证 Redis marker 不会放行 RabbitMQ 端口。"""

        guard, _ = self._build_guard(frozenset({ExternalResourceMarker.REDIS}))

        with pytest.raises(RuntimeError, match=OFFLINE_CONNECTION_BLOCKED_MESSAGE):
            guard.create_socket_connection(RABBITMQ_TEST_ADDRESS)

    def test_redis_marker_when_connecting_redis_port_should_allow(self) -> None:
        """验证 Redis marker 放行 Redis 端口。"""

        guard, _ = self._build_guard(frozenset({ExternalResourceMarker.REDIS}))

        result = guard.create_socket_connection(REDIS_TEST_ADDRESS)

        assert isinstance(result, StubExternalConnectCallable)

    def test_configured_loopback_ports_should_extend_only_matching_resource_markers(self) -> None:
        """验证隔离开发端口仅在对应 marker 和显式 URL 同时存在时放行。"""

        configured_environment = {
            "TEST_DATABASE_URL": "postgresql+psycopg://test@127.0.0.1:55433/codex_test",
            "REDIS_TEST_URL": "redis://127.0.0.1:56380/0",
        }
        postgres_ports = OfflineExternalResourceGuard.resolve_allowed_ports(
            enabled_resources=frozenset({ExternalResourceMarker.POSTGRES}),
            environment=configured_environment,
        )
        redis_ports = OfflineExternalResourceGuard.resolve_allowed_ports(
            enabled_resources=frozenset({ExternalResourceMarker.REDIS}),
            environment=configured_environment,
        )
        postgres_guard, _ = self._build_guard(
            frozenset({ExternalResourceMarker.POSTGRES}),
            allowed_ports=postgres_ports,
        )
        redis_guard, _ = self._build_guard(
            frozenset({ExternalResourceMarker.REDIS}),
            allowed_ports=redis_ports,
        )

        postgres_result = postgres_guard.create_socket_connection(CONFIGURED_POSTGRES_TEST_ADDRESS)
        redis_result = redis_guard.create_socket_connection(CONFIGURED_REDIS_TEST_ADDRESS)

        assert isinstance(postgres_result, StubExternalConnectCallable)
        assert isinstance(redis_result, StubExternalConnectCallable)
        assert CONFIGURED_REDIS_TEST_ADDRESS[1] not in postgres_ports

    def test_configured_public_url_should_not_extend_loopback_port_allowlist(self) -> None:
        """验证外部 URL 即使被显式配置也不能扩展本地端口放行范围。"""

        allowed_ports = OfflineExternalResourceGuard.resolve_allowed_ports(
            enabled_resources=frozenset({ExternalResourceMarker.REDIS}),
            environment={"REDIS_TEST_URL": "redis://198.51.100.10:56380/0"},
        )
        assert CONFIGURED_REDIS_TEST_ADDRESS[1] not in allowed_ports

    def test_unmarked_test_should_not_reach_configured_external_ephemeral_port(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """验证 Docker 映射的 Redis 高端口不能被通用 ephemeral 规则绕过。"""

        monkeypatch.setenv("REDIS_TEST_URL", "redis://127.0.0.1:56380/0")
        guard, _ = self._build_guard(frozenset())

        with pytest.raises(RuntimeError, match=OFFLINE_CONNECTION_BLOCKED_MESSAGE):
            guard.create_socket_connection(CONFIGURED_REDIS_TEST_ADDRESS)

    def test_rabbitmq_marker_when_connecting_rabbitmq_port_should_allow(self) -> None:
        """验证 RabbitMQ marker 只放行消息端口。"""

        guard, _ = self._build_guard(frozenset({ExternalResourceMarker.RABBITMQ}))

        result = guard.create_socket_connection(RABBITMQ_TEST_ADDRESS)

        assert isinstance(result, StubExternalConnectCallable)

    def test_without_marker_when_connecting_public_network_should_reject(self) -> None:
        """验证未声明资源时拒绝公网连接。"""

        guard, _ = self._build_guard(frozenset())

        with pytest.raises(RuntimeError, match=OFFLINE_CONNECTION_BLOCKED_MESSAGE):
            guard.create_socket_connection(PUBLIC_NETWORK_ADDRESS)

    def test_public_network_marker_when_connecting_public_network_should_allow(self) -> None:
        """验证公网 marker 只显式放行非回环公网地址。"""

        guard, _ = self._build_guard(frozenset({ExternalResourceMarker.PUBLIC_NETWORK}))

        result = guard.create_socket_connection(PUBLIC_NETWORK_ADDRESS)

        assert isinstance(result, StubExternalConnectCallable)

    def test_process_local_socketpair_scope_should_not_weaken_normal_connect_guard(
        self,
    ) -> None:
        """验证 Windows socketpair 豁免只覆盖其内部回连，退出后仍拒绝未授权端口。"""

        guard, _ = self._build_guard(frozenset())
        socket_instance = cast(socket.socket, object())

        with guard._allow_process_local_socketpair_connection():
            result = guard.connect_socket(socket_instance, REDIS_TEST_ADDRESS)

        assert isinstance(result, StubExternalConnectCallable)
        with pytest.raises(RuntimeError, match=OFFLINE_CONNECTION_BLOCKED_MESSAGE):
            guard.connect_socket(socket_instance, REDIS_TEST_ADDRESS)

    def test_docker_cli_without_docker_marker_should_reject(self) -> None:
        """验证未声明 Docker marker 时拒绝 CLI 入口。"""

        guard, _ = self._build_guard(frozenset())

        with pytest.raises(RuntimeError, match=OFFLINE_CONNECTION_BLOCKED_MESSAGE):
            guard.launch_process(DOCKER_COMMAND)

    def test_docker_marker_should_allow_cli_and_named_pipe(self) -> None:
        """验证 Docker marker 同时放行 CLI 和命名管道入口。"""

        guard, _ = self._build_guard(frozenset({ExternalResourceMarker.DOCKER}))

        process = guard.launch_process(DOCKER_COMMAND)
        socket_result = guard.connect_socket(cast(socket.socket, object()), DOCKER_NAMED_PIPE)

        assert isinstance(process, StubExternalConnectCallable)
        assert isinstance(socket_result, StubExternalConnectCallable)

    @staticmethod
    def _build_guard(
        enabled_resources: frozenset[ExternalResourceMarker],
        allowed_ports: frozenset[int] | None = None,
    ) -> tuple[OfflineExternalResourceGuard, StubExternalConnectCallable]:
        """构建不接触真实网络的防护对象。"""

        socket_create_connection = StubExternalConnectCallable()
        socket_connect = StubExternalConnectCallable()
        postgres_connect = StubExternalConnectCallable()
        process_launcher = StubExternalConnectCallable()
        return (
            OfflineExternalResourceGuard(
                enabled_resources=enabled_resources,
                socket_create_connection=socket_create_connection,
                socket_connect=socket_connect,
                postgres_connect=postgres_connect,
                process_launcher=process_launcher,
                allowed_ports=allowed_ports,
            ),
            postgres_connect,
        )
