"""
RabbitMQ 消息网关基础设施模块。
"""

from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from urllib.parse import quote, unquote, urlparse

from amqpstorm import AMQPError, UriConnection

from src.core.exception_contract.error_code_catalog_contract import CoreErrorCode
from src.core.exception_contract.http_fault_contract import HttpFaultException

RABBITMQ_URL_PREFIX = "amqp://"
RABBITMQS_URL_PREFIX = "amqps://"
RABBITMQ_DEFAULT_SCHEME = "amqp"
RABBITMQ_DEFAULT_PORT = 5672
RABBITMQ_TIMEOUT_MILLISECONDS_MULTIPLIER = 1000
RABBITMQ_VHOST_PATH_SEPARATOR = "/"
RABBITMQ_ROOT_VHOST = "/"
RABBITMQ_ROOT_VHOST_ENCODED = "%2F"
RABBITMQ_HEALTH_CONNECTED = True
RABBITMQ_HEALTH_DETAIL_EMPTY = None


@dataclass(slots=True)
class RabbitMqRuntimeHealth:
    """
    RabbitMQ 运行时健康快照数据对象。
    """

    connected: bool
    detail: str | None


class RabbitMqMessageGateway:
    """
    RabbitMQ 消息网关类型，用于封装当前模块中的相关行为或状态。
    """

    def __init__(self, rabbitmq_url: str) -> None:
        """
        初始化 RabbitMQ 消息网关。
        """

        self._rabbitmq_url = rabbitmq_url

    def validate_configuration(self) -> bool:
        """
        校验配置。
        """

        return self._rabbitmq_url.startswith((RABBITMQ_URL_PREFIX, RABBITMQS_URL_PREFIX))

    def assert_available(self, *, timeout_seconds: int) -> RabbitMqRuntimeHealth:
        """
        探测 RabbitMQ 可达性。
        """

        if not self.validate_configuration():
            raise HttpFaultException(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                error_code=CoreErrorCode.CONFIG_INVALID,
                message="RabbitMQ 地址配置无效。",
            )
        try:
            connection = UriConnection(self._build_connection_uri(timeout_seconds=timeout_seconds))
            connection.close()
        except AMQPError as exc:
            raise HttpFaultException(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                error_code=CoreErrorCode.RESOURCE_NOT_READY,
                message="RabbitMQ 不可用。",
                detail=str(exc),
            ) from exc
        return RabbitMqRuntimeHealth(
            connected=RABBITMQ_HEALTH_CONNECTED,
            detail=RABBITMQ_HEALTH_DETAIL_EMPTY,
        )

    def _build_connection_uri(self, *, timeout_seconds: int) -> str:
        """
        构建带超时参数的 RabbitMQ 连接地址。
        """

        parsed_url = urlparse(self._rabbitmq_url)
        if parsed_url.hostname is None:
            raise HttpFaultException(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                error_code=CoreErrorCode.CONFIG_INVALID,
                message="RabbitMQ 连接地址缺少主机名。",
            )
        port = parsed_url.port or RABBITMQ_DEFAULT_PORT
        virtual_host_path = self._build_virtual_host_path(parsed_url.path)
        auth_prefix = ""
        if parsed_url.username is not None:
            auth_prefix = parsed_url.username
            if parsed_url.password is not None:
                auth_prefix = f"{auth_prefix}:{parsed_url.password}"
            auth_prefix = f"{auth_prefix}@"
        scheme = parsed_url.scheme or RABBITMQ_DEFAULT_SCHEME
        return (
            f"{scheme}://{auth_prefix}{parsed_url.hostname}:{port}{virtual_host_path}"
            f"?timeout={timeout_seconds * RABBITMQ_TIMEOUT_MILLISECONDS_MULTIPLIER}"
        )

    def build_connection_uri(self, *, timeout_seconds: int) -> str:
        """
        构建可复用的 RabbitMQ 连接地址。
        """

        return self._build_connection_uri(timeout_seconds=timeout_seconds)

    def _build_virtual_host_path(self, parsed_path: str) -> str:
        """
        构建 RabbitMQ URL 使用的虚拟主机路径。

        :param parsed_path: URL 解析出的 path。约束：空路径、``/`` 和 ``//`` 均归一为 root vhost。
        :type parsed_path: str
        :returns: 可安全拼入连接串的 vhost path。
        :rtype: str
        """

        raw_virtual_host = parsed_path.lstrip(RABBITMQ_VHOST_PATH_SEPARATOR)
        if not raw_virtual_host:
            raw_virtual_host = RABBITMQ_ROOT_VHOST_ENCODED
        virtual_host = unquote(raw_virtual_host) or RABBITMQ_ROOT_VHOST
        return RABBITMQ_VHOST_PATH_SEPARATOR + quote(virtual_host, safe="")
