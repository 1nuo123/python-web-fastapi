"""具备生产发布确认与有界队列声明的 Funboost RabbitMQ 发布器。"""

from __future__ import annotations

from typing import Final

import amqpstorm
from amqpstorm.basic import Basic as AmqpStormBasic
from amqpstorm.queue import Queue as AmqpStormQueue
from funboost.funboost_config_deafult import BrokerConnConfig
from funboost.publishers.base_publisher import deco_mq_conn_error
from funboost.publishers.rabbitmq_complex_routing_publisher import (
    RabbitmqComplexRoutingPublisher,
)

from src.infrastructure.task.rabbitmq_message_gateway import RabbitMqMessageGateway

RABBITMQ_DELIVERY_MODE_PERSISTENT = 2
RABBITMQ_DELIVERY_MODE_TRANSIENT = 1
RABBITMQ_PUBLISH_MANDATORY = True
RABBITMQ_QUEUE_MAX_LENGTH_ARGUMENT: Final = "x-max-length"
RABBITMQ_QUEUE_OVERFLOW_ARGUMENT: Final = "x-overflow"
RABBITMQ_QUEUE_OVERFLOW_REJECT_PUBLISH: Final = "reject-publish"
RABBITMQ_DEAD_LETTER_EXCHANGE_ARGUMENT: Final = "x-dead-letter-exchange"
RABBITMQ_QUEUE_MAX_LENGTH_CONFIG: Final = "queue_max_length"
RABBITMQ_PREFETCH_COUNT_CONFIG: Final = "prefetch_count"
RABBITMQ_DEAD_LETTER_EXCHANGE_CONFIG: Final = "dead_letter_exchange_name"
RABBITMQ_MESSAGE_PERSISTENT_CONFIG: Final = "message_persistent"
RABBITMQ_PUBLISHER_CONFIRM_CONFIG: Final = "publisher_confirm_enabled"
RABBITMQ_PUBLISHER_CONFIRM_TIMEOUT_CONFIG: Final = "publisher_confirm_timeout_seconds"
RABBITMQ_ROUTING_KEY_CONFIG: Final = "routing_key_for_publish"
RABBITMQ_HEADERS_CONFIG: Final = "headers_for_publish"
RABBITMQ_PRIORITY_CONFIG: Final = "priority"
RABBITMQ_ROUTING_KEY_BIND_CONFIG: Final = "routing_key_for_bind"
RABBITMQ_PUBLISH_NACK_MESSAGE = "RabbitMQ 发布确认返回拒绝。"
RABBITMQ_PUBLISH_UNROUTABLE_MESSAGE = "RabbitMQ mandatory 发布未路由到任务队列。"


class ConfirmedFunboostRabbitMqPublisher(RabbitmqComplexRoutingPublisher):
    """为 Funboost 主发布链提供持久化、确认和有界队列语义。"""

    def init_broker(self) -> None:
        """建立带冻结确认超时的 AMQP 连接并声明生产拓扑。"""

        current_channel = getattr(self, "channel", None)
        if current_channel is not None and getattr(current_channel, "is_open", True):
            return
        timeout_seconds = int(
            self.publisher_params.broker_exclusive_config[RABBITMQ_PUBLISHER_CONFIRM_TIMEOUT_CONFIG]
        )
        connection_uri = RabbitMqMessageGateway(BrokerConnConfig.RABBITMQ_URL).build_connection_uri(
            timeout_seconds=timeout_seconds
        )
        self.connection = amqpstorm.UriConnection(connection_uri)
        self.channel = self.connection.channel(rpc_timeout=timeout_seconds)
        self.channel_wrapper_by_ampqstormbaic = AmqpStormBasic(self.channel)
        self._declare_topology()
        if self.publisher_params.broker_exclusive_config[RABBITMQ_PUBLISHER_CONFIRM_CONFIG]:
            self.channel.confirm_deliveries()

    def _declare_topology(self) -> None:
        """声明交换机、有界主队列、死信交换机和唯一绑定。"""

        queue_arguments: dict[str, int | str] = {
            RABBITMQ_QUEUE_MAX_LENGTH_ARGUMENT: int(
                self.publisher_params.broker_exclusive_config[RABBITMQ_QUEUE_MAX_LENGTH_CONFIG]
            ),
            RABBITMQ_QUEUE_OVERFLOW_ARGUMENT: RABBITMQ_QUEUE_OVERFLOW_REJECT_PUBLISH,
        }
        dead_letter_exchange_name = str(
            self.publisher_params.broker_exclusive_config[RABBITMQ_DEAD_LETTER_EXCHANGE_CONFIG]
        )
        if dead_letter_exchange_name:
            queue_arguments[RABBITMQ_DEAD_LETTER_EXCHANGE_ARGUMENT] = dead_letter_exchange_name
            self.channel.exchange.declare(
                exchange=dead_letter_exchange_name,
                exchange_type=self._exchange_type,
                durable=self._exchange_declare_durable,
            )
        if self._exchange_name:
            self.channel.exchange.declare(
                exchange=self._exchange_name,
                exchange_type=self._exchange_type,
                durable=self._exchange_declare_durable,
            )
        self.queue_declare_params["arguments"] = queue_arguments
        queue = AmqpStormQueue(self.channel)
        queue.declare(**self.queue_declare_params)
        queue.bind(
            queue=self._queue_name,
            exchange=self._exchange_name,
            routing_key=self.publisher_params.broker_exclusive_config[
                RABBITMQ_ROUTING_KEY_BIND_CONFIG
            ],
        )

    @deco_mq_conn_error
    def _publish_impl(self, msg: str) -> None:
        """发布持久消息并等待 broker 确认。"""

        routing_key = self._get_from_other_extra_params(RABBITMQ_ROUTING_KEY_CONFIG, msg)
        if routing_key is None:
            routing_key = self._routing_key_for_publish
        result = self.channel.basic.publish(
            body=msg,
            routing_key=routing_key,
            exchange=self._exchange_name,
            mandatory=RABBITMQ_PUBLISH_MANDATORY,
            properties={
                "delivery_mode": (
                    RABBITMQ_DELIVERY_MODE_PERSISTENT
                    if self.publisher_params.broker_exclusive_config[
                        RABBITMQ_MESSAGE_PERSISTENT_CONFIG
                    ]
                    else RABBITMQ_DELIVERY_MODE_TRANSIENT
                ),
                "priority": self._get_from_other_extra_params(
                    RABBITMQ_PRIORITY_CONFIG,
                    msg,
                ),
                "headers": self._get_from_other_extra_params(
                    RABBITMQ_HEADERS_CONFIG,
                    msg,
                ),
            },
        )
        self.channel.check_for_exceptions()
        if result is False:
            raise RuntimeError(RABBITMQ_PUBLISH_NACK_MESSAGE)
        if result is not True:
            raise RuntimeError(RABBITMQ_PUBLISH_UNROUTABLE_MESSAGE)
