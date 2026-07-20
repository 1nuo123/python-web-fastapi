"""
RabbitMQ 消息网关单元测试模块。
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.infrastructure.task.rabbitmq_message_gateway import (
    RABBITMQ_TIMEOUT_MILLISECONDS_MULTIPLIER,
    RabbitMqMessageGateway,
)

RABBITMQ_TIMEOUT_SECONDS = 3
RABBITMQ_ROOT_VHOST_SUFFIX = "/%2F"
RABBITMQ_DOUBLE_SLASH_FRAGMENT = ":5672//"
RABBITMQ_ROOT_VHOST_URLS = (
    "amqp://guest:guest@127.0.0.1:5672",
    "amqp://guest:guest@127.0.0.1:5672/",
    "amqp://guest:guest@127.0.0.1:5672//",
    "amqp://guest:guest@127.0.0.1:5672/%2F",
)


class TestRabbitMqMessageGatewayUnit:
    """
    RabbitMQ 消息网关单元测试集合。
    """

    def test_validate_configuration_when_amqp_url_should_return_true(self) -> None:
        """
        验证网关当地址合法应返回真。
        """

        gateway = RabbitMqMessageGateway("amqp://guest:guest@127.0.0.1:5672/")

        assert gateway.validate_configuration() is True

    def test_assert_available_when_configuration_invalid_should_fail(self) -> None:
        """
        验证网关当配置无效应失败。
        """

        gateway = RabbitMqMessageGateway("http://127.0.0.1:5672/")

        with pytest.raises(HttpFaultException) as exc_info:
            gateway.assert_available(timeout_seconds=1)

        assert exc_info.value.error_code == "system.config.invalid"

    def test_assert_available_when_connection_ok_should_return_health(
        self,
    ) -> None:
        """
        验证网关当连接正常应返回健康快照。
        """

        gateway = RabbitMqMessageGateway("amqp://guest:guest@127.0.0.1:5672/")

        with patch(
            "src.infrastructure.task.rabbitmq_message_gateway.UriConnection"
        ) as uri_connection:
            uri_connection.return_value.close.return_value = None
            health = gateway.assert_available(timeout_seconds=RABBITMQ_TIMEOUT_SECONDS)

        assert health.connected is True
        assert health.detail is None
        uri_connection.assert_called_once()

    def test_assert_available_when_root_vhost_variants_should_use_encoded_path(
        self,
    ) -> None:
        """
        验证 root vhost 的多种 URL 写法都会归一为编码路径。
        """

        expected_timeout = RABBITMQ_TIMEOUT_SECONDS * RABBITMQ_TIMEOUT_MILLISECONDS_MULTIPLIER
        for rabbitmq_url in RABBITMQ_ROOT_VHOST_URLS:
            gateway = RabbitMqMessageGateway(rabbitmq_url)
            with patch(
                "src.infrastructure.task.rabbitmq_message_gateway.UriConnection"
            ) as uri_connection:
                uri_connection.return_value.close.return_value = None
                gateway.assert_available(timeout_seconds=RABBITMQ_TIMEOUT_SECONDS)

            called_uri = uri_connection.call_args.args[0]
            assert RABBITMQ_DOUBLE_SLASH_FRAGMENT not in called_uri
            assert called_uri.endswith(f"{RABBITMQ_ROOT_VHOST_SUFFIX}?timeout={expected_timeout}")
