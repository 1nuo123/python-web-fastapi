"""Funboost RabbitMQ 确认发布器单元测试。"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.infrastructure.task.confirmed_funboost_rabbitmq_publisher import (
    RABBITMQ_DELIVERY_MODE_PERSISTENT,
    RABBITMQ_PUBLISH_NACK_MESSAGE,
    ConfirmedFunboostRabbitMqPublisher,
)

PUBLISHER_TEST_MESSAGE = (
    '{"task_message":{},"extra":{"other_extra_params":{"routing_key_for_publish":"task.route"}}}'
)


class StubConfirmedPublishBasic:
    """记录 AMQP basic.publish 调用。"""

    def __init__(self, result: bool) -> None:
        """初始化发布确认结果。"""

        self._result = result
        self.properties: dict[str, object] | None = None

    def publish(self, **kwargs: object) -> bool:
        """记录发布属性并返回确认结果。"""

        properties = kwargs["properties"]
        assert isinstance(properties, dict)
        self.properties = properties
        return self._result


class StubConfirmedPublishChannel:
    """模拟 AMQP 信道。"""

    def __init__(self, result: bool) -> None:
        """初始化 basic 发布器。"""

        self.basic = StubConfirmedPublishBasic(result)
        self.exception_checked = False

    def check_for_exceptions(self) -> None:
        """记录 mandatory 异常检查。"""

        self.exception_checked = True


@dataclass(slots=True)
class StubPublisherParams:
    """确认发布器所需参数。"""

    broker_exclusive_config: dict[str, object]


class TestConfirmedFunboostRabbitMqPublisherUnit:
    """验证生产主链的持久化和确认拒绝语义。"""

    def test_publish_when_broker_confirms_should_use_persistent_delivery(self) -> None:
        """验证 broker 确认成功时使用持久化消息并检查 mandatory 异常。"""

        publisher, channel = self._build_publisher(confirm_result=True)

        publisher._publish_impl(PUBLISHER_TEST_MESSAGE)  # noqa: SLF001

        assert channel.exception_checked is True
        assert channel.basic.properties is not None
        assert channel.basic.properties["delivery_mode"] == RABBITMQ_DELIVERY_MODE_PERSISTENT

    def test_publish_when_broker_nacks_should_raise_failure(self) -> None:
        """验证 broker 返回 NACK 时发布失败而不误记成功。"""

        publisher, _channel = self._build_publisher(confirm_result=False)

        with pytest.raises(RuntimeError, match=RABBITMQ_PUBLISH_NACK_MESSAGE):
            publisher._publish_impl(PUBLISHER_TEST_MESSAGE)  # noqa: SLF001

    def _build_publisher(
        self,
        *,
        confirm_result: bool,
    ) -> tuple[ConfirmedFunboostRabbitMqPublisher, StubConfirmedPublishChannel]:
        """构建不建立网络连接的确认发布器。"""

        publisher = object.__new__(ConfirmedFunboostRabbitMqPublisher)
        channel = StubConfirmedPublishChannel(confirm_result)
        publisher.channel = channel
        publisher.has_init_broker = 1
        publisher.publisher_params = StubPublisherParams(
            broker_exclusive_config={"message_persistent": True}
        )
        publisher._exchange_name = "task.exchange"  # noqa: SLF001
        publisher._routing_key_for_publish = "task.route"  # noqa: SLF001
        return publisher, channel
