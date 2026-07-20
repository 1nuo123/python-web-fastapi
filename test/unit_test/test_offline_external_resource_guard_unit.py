"""离线外部资源逐项授权单元测试。"""

from __future__ import annotations

import pytest

from test.conftest import (
    OFFLINE_CONNECTION_BLOCKED_MESSAGE,
    ExternalResourceMarker,
    OfflineExternalResourceGuard,
)

REDIS_TEST_ADDRESS = ("127.0.0.1", 6379)
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

    def test_docker_cli_without_docker_marker_should_reject(self) -> None:
        """验证未声明 Docker marker 时拒绝 CLI 入口。"""

        guard, _ = self._build_guard(frozenset())

        with pytest.raises(RuntimeError, match=OFFLINE_CONNECTION_BLOCKED_MESSAGE):
            guard.launch_process(DOCKER_COMMAND)

    def test_docker_marker_should_allow_cli_and_named_pipe(self) -> None:
        """验证 Docker marker 同时放行 CLI 和命名管道入口。"""

        guard, _ = self._build_guard(frozenset({ExternalResourceMarker.DOCKER}))

        process = guard.launch_process(DOCKER_COMMAND)
        socket_result = guard.connect_socket(object(), DOCKER_NAMED_PIPE)

        assert isinstance(process, StubExternalConnectCallable)
        assert isinstance(socket_result, StubExternalConnectCallable)

    @staticmethod
    def _build_guard(
        enabled_resources: frozenset[ExternalResourceMarker],
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
            ),
            postgres_connect,
        )
