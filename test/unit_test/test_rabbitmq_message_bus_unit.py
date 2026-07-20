"""
RabbitMQ 消息总线单元测试模块。
"""

from __future__ import annotations

from unittest.mock import Mock, patch

import pytest
from amqpstorm import AMQPError

from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.task_contract.message_bus_contract import (
    MessageBusBackend,
    TaskMessageEnvelope,
    TaskMessageHeader,
    TaskMessagePayload,
)
from src.core.task_contract.task_runtime_contract import RabbitMqMessageBackendDetail
from src.infrastructure.task.rabbitmq_message_bus import (
    RABBITMQ_CONTENT_TYPE_JSON,
    RABBITMQ_DELIVERY_MODE_PERSISTENT,
    RABBITMQ_HEADER_REQUEST_ID,
    RABBITMQ_HEADER_TRACE_ID,
    RABBITMQ_PUBLISH_MANDATORY,
    RabbitMqMessageBus,
)

RABBITMQ_UNIT_URL = "amqp://guest:guest@127.0.0.1:5672/"
RABBITMQ_UNIT_EXCHANGE = "task.direct"
RABBITMQ_UNIT_EXCHANGE_TYPE = "direct"
RABBITMQ_UNIT_JOB_KIND = "rabbitmq.unit.job"
RABBITMQ_UNIT_MESSAGE_ID = "rabbitmq-message-unit-1"
RABBITMQ_UNIT_REQUEST_ID = "rabbitmq-request-unit-1"
RABBITMQ_UNIT_TRACE_ID = "rabbitmq-trace-unit-1"
RABBITMQ_UNIT_CREATED_AT_EPOCH = 1700000000
RABBITMQ_UNIT_DEDUPLICATION_KEY = "rabbitmq-dedupe-unit-1"
RABBITMQ_UNIT_RETRY_LIMIT = 1
RABBITMQ_UNIT_PAYLOAD_KIND = "RabbitMqUnitPayload"
RABBITMQ_UNIT_PAYLOAD_JSON = '{"kind":"rabbitmq_unit","schema_version":"1.0"}'
RABBITMQ_UNIT_TIMEOUT_SECONDS = 5


class TestRabbitMqMessageBusUnit:
    """
    RabbitMQ 消息总线单元测试集合。
    """

    def test_publish_should_declare_exchange_and_publish_properties(self) -> None:
        """
        验证发布时声明交换机并携带标准消息属性。
        """

        channel = self._build_channel()
        connection = Mock()
        connection.channel.return_value = channel
        message = self._build_message()

        with patch(
            "src.infrastructure.task.rabbitmq_message_bus.UriConnection",
            return_value=connection,
        ) as uri_connection:
            bus = RabbitMqMessageBus(detail=self._build_detail())
            try:
                result = bus.publish(message)
            finally:
                bus.close()

        uri_connection.assert_called_once()
        connection.channel.assert_called_once_with(rpc_timeout=RABBITMQ_UNIT_TIMEOUT_SECONDS)
        channel.exchange.declare.assert_called_once_with(
            exchange=RABBITMQ_UNIT_EXCHANGE,
            exchange_type=RABBITMQ_UNIT_EXCHANGE_TYPE,
            durable=True,
        )
        channel.confirm_deliveries.assert_called_once()
        publish_call = channel.basic.publish.call_args.kwargs
        assert publish_call["exchange"] == RABBITMQ_UNIT_EXCHANGE
        assert publish_call["routing_key"] == RABBITMQ_UNIT_JOB_KIND
        assert publish_call["mandatory"] is RABBITMQ_PUBLISH_MANDATORY
        assert message.header.message_id in publish_call["body"]
        assert publish_call["properties"]["content_type"] == RABBITMQ_CONTENT_TYPE_JSON
        assert publish_call["properties"]["delivery_mode"] == RABBITMQ_DELIVERY_MODE_PERSISTENT
        assert publish_call["properties"]["message_id"] == RABBITMQ_UNIT_MESSAGE_ID
        assert publish_call["properties"]["correlation_id"] == RABBITMQ_UNIT_REQUEST_ID
        assert (
            publish_call["properties"]["headers"][RABBITMQ_HEADER_REQUEST_ID]
            == RABBITMQ_UNIT_REQUEST_ID
        )
        assert (
            publish_call["properties"]["headers"][RABBITMQ_HEADER_TRACE_ID]
            == RABBITMQ_UNIT_TRACE_ID
        )
        assert result.published is True
        assert result.routed is True
        assert result.message_id == RABBITMQ_UNIT_MESSAGE_ID
        assert result.detail.kind == "message_publish_succeeded"

    def test_publish_when_confirm_nack_should_raise_fault(self) -> None:
        """
        验证发布确认拒绝时抛出业务异常。
        """

        channel = self._build_channel()
        channel.basic.publish.return_value = False
        connection = Mock()
        connection.channel.return_value = channel
        bus = RabbitMqMessageBus(detail=self._build_detail())

        with patch(
            "src.infrastructure.task.rabbitmq_message_bus.UriConnection",
            return_value=connection,
        ):
            try:
                with pytest.raises(HttpFaultException):
                    bus.publish(self._build_message())
            finally:
                bus.close()

    def test_publish_when_mandatory_unroutable_should_raise_fault(self) -> None:
        """
        验证 mandatory 未路由消息会被识别为发布失败。
        """

        channel = self._build_channel()
        channel.check_for_exceptions.side_effect = AMQPError(
            "Message not delivered",
        )
        connection = Mock()
        connection.channel.return_value = channel
        bus = RabbitMqMessageBus(detail=self._build_detail())

        with patch(
            "src.infrastructure.task.rabbitmq_message_bus.UriConnection",
            return_value=connection,
        ):
            try:
                with pytest.raises(HttpFaultException) as exc_info:
                    bus.publish(self._build_message())
            finally:
                bus.close()

        assert "RabbitMQ 消息发布失败" in str(exc_info.value)

    def test_publish_when_confirm_disabled_should_not_claim_routed(self) -> None:
        """
        验证未启用发布确认时不声明路由成功。
        """

        channel = self._build_channel()
        connection = Mock()
        connection.channel.return_value = channel
        bus = RabbitMqMessageBus(
            detail=self._build_detail(publisher_confirm_enabled=False),
        )

        with patch(
            "src.infrastructure.task.rabbitmq_message_bus.UriConnection",
            return_value=connection,
        ):
            try:
                result = bus.publish(self._build_message())
            finally:
                bus.close()

        channel.confirm_deliveries.assert_not_called()
        assert result.published is True
        assert result.routed is False

    def test_close_should_release_channel_and_connection_once(self) -> None:
        """
        验证关闭会释放信道和连接并支持重复关闭。
        """

        channel = self._build_channel()
        connection = Mock()
        connection.channel.return_value = channel
        bus = RabbitMqMessageBus(detail=self._build_detail())

        with patch(
            "src.infrastructure.task.rabbitmq_message_bus.UriConnection",
            return_value=connection,
        ):
            bus.publish(self._build_message())
            bus.close()
            bus.close()

        channel.close.assert_called_once()
        connection.close.assert_called_once()
        assert bus.backend == MessageBusBackend.RABBITMQ

    def _build_channel(self) -> Mock:
        """
        构建 RabbitMQ 信道替身。
        """

        channel = Mock()
        channel.exchange.declare.return_value = None
        channel.confirm_deliveries.return_value = None
        channel.basic.publish.return_value = True
        channel.check_for_exceptions.return_value = None
        channel.close.return_value = None
        return channel

    def _build_detail(
        self,
        *,
        publisher_confirm_enabled: bool = True,
    ) -> RabbitMqMessageBackendDetail:
        """
        构建 RabbitMQ 消息后端配置。
        """

        return RabbitMqMessageBackendDetail(
            rabbitmq_url=RABBITMQ_UNIT_URL,
            startup_probe_enabled=False,
            startup_probe_timeout_seconds=1,
            task_exchange_name=RABBITMQ_UNIT_EXCHANGE,
            task_exchange_type=RABBITMQ_UNIT_EXCHANGE_TYPE,
            task_exchange_durable=True,
            task_message_persistent=True,
            publisher_confirm_enabled=publisher_confirm_enabled,
            publisher_confirm_timeout_seconds=RABBITMQ_UNIT_TIMEOUT_SECONDS,
        )

    def _build_message(self) -> TaskMessageEnvelope:
        """
        构建任务消息。
        """

        return TaskMessageEnvelope(
            header=TaskMessageHeader(
                message_id=RABBITMQ_UNIT_MESSAGE_ID,
                request_id=RABBITMQ_UNIT_REQUEST_ID,
                trace_id=RABBITMQ_UNIT_TRACE_ID,
                created_at_epoch=RABBITMQ_UNIT_CREATED_AT_EPOCH,
            ),
            payload=TaskMessagePayload(
                job_kind=RABBITMQ_UNIT_JOB_KIND,
                deduplication_key=RABBITMQ_UNIT_DEDUPLICATION_KEY,
                retry_limit=RABBITMQ_UNIT_RETRY_LIMIT,
                payload_kind=RABBITMQ_UNIT_PAYLOAD_KIND,
                payload_json=RABBITMQ_UNIT_PAYLOAD_JSON,
            ),
        )
