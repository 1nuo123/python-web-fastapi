"""应用显式预取上限的 Funboost RabbitMQ 消费器。"""

from __future__ import annotations

from collections.abc import Callable
from typing import ParamSpec, TypeVar, cast

import amqpstorm
from funboost.consumers.rabbitmq_complex_routing_consumer import (
    RabbitmqComplexRoutingConsumer,
)

from src.infrastructure.task.confirmed_funboost_rabbitmq_publisher import (
    RABBITMQ_PREFETCH_COUNT_CONFIG,
)

RABBITMQ_CONSUMER_NO_ACK_CONFIG = "no_ack"

_P = ParamSpec("_P")
_R = TypeVar("_R")


class BoundedFunboostRabbitMqConsumer(RabbitmqComplexRoutingConsumer):
    """使用配置化 QoS 限制单消费者未确认消息数量。"""

    def keep_circulating(
        self,
        time_sleep: float = 0.001,
        exit_if_function_run_sucsess: bool = False,
        is_display_detail_exception: bool = True,
        block: bool = True,
        daemon: bool = False,
    ) -> Callable[[Callable[_P, _R]], Callable[_P, _R]]:
        """让非阻塞循环使用守护线程，由项目生命周期负责显式停机。"""

        return cast(
            Callable[[Callable[_P, _R]], Callable[_P, _R]],
            super().keep_circulating(
                time_sleep=time_sleep,
                exit_if_function_run_sucsess=exit_if_function_run_sucsess,
                is_display_detail_exception=is_display_detail_exception,
                block=block,
                daemon=daemon or not block,
            ),
        )

    def _dispatch_task(self) -> None:
        """按冻结预取上限消费消息。"""

        def submit_message(message: amqpstorm.Message) -> None:
            self._submit_task(
                {
                    "amqpstorm_message": message,
                    "body": message.body,
                }
            )

        publisher = self._rp
        prefetch_count = int(
            self.consumer_params.broker_exclusive_config[RABBITMQ_PREFETCH_COUNT_CONFIG]
        )
        publisher.channel_wrapper_by_ampqstormbaic.qos(prefetch_count)
        publisher.channel_wrapper_by_ampqstormbaic.consume(
            callback=submit_message,
            queue=self.queue_name,
            no_ack=self.consumer_params.broker_exclusive_config[RABBITMQ_CONSUMER_NO_ACK_CONFIG],
        )
        publisher.channel.start_consuming(auto_decode=True)
