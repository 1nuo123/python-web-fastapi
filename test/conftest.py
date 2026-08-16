"""离线测试公共环境与外部资源防护。"""

from __future__ import annotations

import os
import socket
import subprocess
from collections.abc import Iterator
from enum import StrEnum
from pathlib import Path
from typing import Final, NoReturn, Protocol, cast
from urllib.parse import quote

import psycopg
import pytest

from src.api.testing.test_app_factory import (
    TestPersistenceBackend,
    TestPersistenceBackendSelector,
)
from src.infrastructure.settings.dotenv_settings_loader import DotenvSettingsLoader
from test.integration_database_fixture import integration_database as integration_database

TEST_APP_ENVIRONMENT = "test"
TEST_JWT_SECRET = "test-secret-2026-with-safe-length"
TEST_BOOTSTRAP_ADMIN_PASSWORD = "admin"
ROOT_DOTENV_PATH = Path(".env")
REDIS_PASSWORD_ENVIRONMENT_VARIABLE = "REDIS_PASSWORD"
REDIS_HOST_PORT_ENVIRONMENT_VARIABLE = "REDIS_HOST_PORT"
REDIS_URL_ENVIRONMENT_VARIABLE = "REDIS_URL"
REDIS_TEST_URL_ENVIRONMENT_VARIABLE = "REDIS_TEST_URL"
DEFAULT_REDIS_HOST_PORT = "56379"
REDIS_DATABASE_NUMBER = 0
OFFLINE_CONNECTION_BLOCKED_MESSAGE = "离线测试禁止连接外部资源；请声明对应资源 marker。"
NETWORK_ADDRESS_PART_COUNT = 2
EPHEMERAL_PORT_MINIMUM = 49152
LOOPBACK_ADDRESSES: Final = frozenset({"127.0.0.1", "::1"})


class ExternalResourceMarker(StrEnum):
    """测试可显式申请的外部资源。"""

    POSTGRES = "postgres"
    REDIS = "redis"
    RABBITMQ = "rabbitmq"
    DOCKER = "docker"
    PUBLIC_NETWORK = "public_network"


RESOURCE_ALLOWED_PORTS: Final = {
    ExternalResourceMarker.POSTGRES: frozenset({5432, 55432}),
    ExternalResourceMarker.REDIS: frozenset({6379, 56379}),
    ExternalResourceMarker.RABBITMQ: frozenset({5672, 15672}),
    ExternalResourceMarker.DOCKER: frozenset({2375, 2376}),
    ExternalResourceMarker.PUBLIC_NETWORK: frozenset(),
}


class ExternalConnectCallable(Protocol):
    """被外连防护包装的连接调用协议。"""

    def __call__(self, *args: object, **kwargs: object) -> object:
        """执行底层连接。"""


DOCKER_EXECUTABLE_NAMES: Final = frozenset({"docker", "docker.exe"})
DOCKER_NAMED_PIPE_PREFIXES: Final = ("//./pipe/docker_engine", r"\\.\pipe\docker_engine")


class TestEnvironmentInitializer:
    """初始化仅作用于 pytest 进程的测试环境。"""

    @classmethod
    def initialize(cls) -> None:
        """加载测试环境并设置安全默认值。"""

        dotenv_values = (
            DotenvSettingsLoader()
            .load(
                dotenv_path=ROOT_DOTENV_PATH,
                environment=TEST_APP_ENVIRONMENT,
                enabled=True,
            )
            .variables
        )
        os.environ.setdefault("APP_ENV", TEST_APP_ENVIRONMENT)
        os.environ.setdefault("JWT_SECRET", TEST_JWT_SECRET)
        os.environ.setdefault(
            "AUTH_BOOTSTRAP_ADMIN_PASSWORD",
            TEST_BOOTSTRAP_ADMIN_PASSWORD,
        )
        test_database_url = dotenv_values.get("TEST_DATABASE_URL")
        if test_database_url:
            os.environ.setdefault("DATABASE_URL", test_database_url)
        redis_password = dotenv_values.get(REDIS_PASSWORD_ENVIRONMENT_VARIABLE)
        if redis_password:
            redis_host_port = dotenv_values.get(
                REDIS_HOST_PORT_ENVIRONMENT_VARIABLE,
                DEFAULT_REDIS_HOST_PORT,
            )
            encoded_password = quote(redis_password, safe="")
            redis_url = (
                f"redis://:{encoded_password}@127.0.0.1:{redis_host_port}/{REDIS_DATABASE_NUMBER}"
            )
            os.environ.setdefault(REDIS_URL_ENVIRONMENT_VARIABLE, redis_url)
            os.environ.setdefault(REDIS_TEST_URL_ENVIRONMENT_VARIABLE, redis_url)


class OfflineExternalResourceGuard:
    """阻止未显式声明资源的测试建立真实网络连接。"""

    def __init__(
        self,
        *,
        enabled_resources: frozenset[ExternalResourceMarker],
        socket_create_connection: ExternalConnectCallable,
        socket_connect: ExternalConnectCallable,
        postgres_connect: ExternalConnectCallable,
        process_launcher: ExternalConnectCallable,
    ) -> None:
        """保存逐资源授权和原始连接入口。"""

        self._enabled_resources = enabled_resources
        self._socket_create_connection = socket_create_connection
        self._socket_connect = socket_connect
        self._postgres_connect = postgres_connect
        self._process_launcher = process_launcher

    @staticmethod
    def enforce(
        request: pytest.FixtureRequest,
        monkeypatch: pytest.MonkeyPatch,
    ) -> Iterator[None]:
        """在离线测试期间替换数据库和套接字连接入口。"""

        enabled_resources = frozenset(
            marker
            for marker in ExternalResourceMarker
            if request.node.get_closest_marker(marker.value) is not None
        )
        postgres_enabled = ExternalResourceMarker.POSTGRES in enabled_resources
        backend = (
            TestPersistenceBackend.CONFIGURED if postgres_enabled else TestPersistenceBackend.SQLITE
        )
        backend_token = TestPersistenceBackendSelector.activate(backend)
        guard = OfflineExternalResourceGuard(
            enabled_resources=enabled_resources,
            socket_create_connection=cast(ExternalConnectCallable, socket.create_connection),
            socket_connect=cast(ExternalConnectCallable, socket.socket.connect),
            postgres_connect=cast(ExternalConnectCallable, psycopg.connect),
            process_launcher=cast(ExternalConnectCallable, subprocess.Popen),
        )

        def guarded_socket_connect(socket_instance: socket.socket, address: object) -> object:
            """把套接字实例显式转发到当前测试的逐资源防护。"""

            return guard.connect_socket(socket_instance, address)

        try:
            monkeypatch.setattr(psycopg, "connect", guard.connect_postgres)
            monkeypatch.setattr(socket, "create_connection", guard.create_socket_connection)
            monkeypatch.setattr(socket.socket, "connect", guarded_socket_connect)
            monkeypatch.setattr(subprocess, "Popen", guard.launch_process)
            yield
        finally:
            TestPersistenceBackendSelector.reset(backend_token)

    @staticmethod
    def reject(*_args: object, **_kwargs: object) -> NoReturn:
        """拒绝未声明的外部连接。"""

        raise RuntimeError(OFFLINE_CONNECTION_BLOCKED_MESSAGE)

    def connect_postgres(self, *args: object, **kwargs: object) -> object:
        """只在当前测试声明 PostgreSQL marker 时放行连接。"""

        if ExternalResourceMarker.POSTGRES not in self._enabled_resources:
            self.reject()
        return self._postgres_connect(*args, **kwargs)

    def create_socket_connection(self, address: object, *args: object, **kwargs: object) -> object:
        """按目标端口与资源 marker 放行套接字连接。"""

        self._validate_address(address)
        return self._socket_create_connection(address, *args, **kwargs)

    def connect_socket(self, socket_instance: socket.socket, address: object) -> object:
        """覆盖直接 ``socket.connect`` 入口并执行逐资源授权。"""

        self._validate_address(address)
        return self._socket_connect(socket_instance, address)

    def launch_process(self, *args: object, **kwargs: object) -> object:
        """阻止未声明 Docker marker 的测试通过 CLI 访问守护进程。"""

        command = args[0] if args else kwargs.get("args")
        if self._contains_docker_executable(command):
            if ExternalResourceMarker.DOCKER not in self._enabled_resources:
                self.reject()
        return self._process_launcher(*args, **kwargs)

    @staticmethod
    def _contains_docker_executable(command: object) -> bool:
        """识别列表或字符串命令中的 Docker 可执行文件。"""

        if isinstance(command, str):
            tokens = command.replace('"', " ").replace("'", " ").split()
        elif isinstance(command, (list, tuple)):
            tokens = [str(token) for token in command]
        else:
            return False
        return any(Path(token).name.lower() in DOCKER_EXECUTABLE_NAMES for token in tokens)

    def _validate_address(self, address: object) -> None:
        """拒绝未由对应资源 marker 授权的网络端口。"""

        if isinstance(address, str) and address.startswith(DOCKER_NAMED_PIPE_PREFIXES):
            if ExternalResourceMarker.DOCKER in self._enabled_resources:
                return
            self.reject()
        if not isinstance(address, tuple) or len(address) < NETWORK_ADDRESS_PART_COUNT:
            self.reject()
        port = address[1]
        host = address[0]
        if not isinstance(port, int):
            self.reject()
        if (
            isinstance(host, str)
            and host not in LOOPBACK_ADDRESSES
            and ExternalResourceMarker.PUBLIC_NETWORK in self._enabled_resources
        ):
            return
        if isinstance(host, str) and port >= EPHEMERAL_PORT_MINIMUM and host in LOOPBACK_ADDRESSES:
            return
        allowed_ports = frozenset(
            port_number
            for resource in self._enabled_resources
            for port_number in RESOURCE_ALLOWED_PORTS[resource]
        )
        if port not in allowed_ports:
            self.reject()


TestEnvironmentInitializer.initialize()
offline_external_resource_guard = pytest.fixture(autouse=True)(OfflineExternalResourceGuard.enforce)
