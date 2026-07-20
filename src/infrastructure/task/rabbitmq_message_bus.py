"""
RabbitMQ 消息总线基础设施模块。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from http import HTTPStatus
from typing import Final, TypedDict, cast

from amqpstorm import AMQPError, Channel, UriConnection

from src.core.exception_contract.error_code_catalog_contract import CoreErrorCode
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.task_contract.message_bus_contract import (
    MessageBus,
    MessageBusBackend,
    MessagePublishResult,
    TaskMessageEnvelope,
)
from src.core.task_contract.task_runtime_contract import RabbitMqMessageBackendDetail
from src.infrastructure.task.rabbitmq_message_gateway import RabbitMqMessageGateway

RABBITMQ_CONTENT_TYPE_JSON = "application/json"
RABBITMQ_DELIVERY_MODE_PERSISTENT = 2
RABBITMQ_DELIVERY_MODE_TRANSIENT = 1
RABBITMQ_HEADER_REQUEST_ID: Final = "request_id"
RABBITMQ_HEADER_TRACE_ID: Final = "trace_id"
RABBITMQ_PUBLISH_MANDATORY = True
RABBITMQ_PUBLISH_FAILED_MESSAGE = "RabbitMQ 消息发布失败。"
RABBITMQ_PUBLISH_NACK_MESSAGE = "RabbitMQ 发布确认返回拒绝。"
RABBITMQ_CLOSE_FAILED_MESSAGE = "RabbitMQ 消息总线关闭失败。"
RABBITMQ_PUBLISH_RESULT_UNROUTABLE_DETAIL = "RabbitMQ mandatory 发布未路由到队列。"


class RabbitMqPublishHeaderMapping(TypedDict, total=False):
    """
    RabbitMQ 发布头映射。
    """

    request_id: str
    trace_id: str


class RabbitMqPublishPropertyMapping(TypedDict):
    """
    RabbitMQ 发布属性映射。
    """

    content_type: str
    delivery_mode: int
    message_id: str
    correlation_id: str
    timestamp: datetime
    headers: RabbitMqPublishHeaderMapping


@dataclass(frozen=True, slots=True)
class RabbitMqPublishHeaders:
    """
    RabbitMQ 发布头。
    """

    request_id: str
    trace_id: str | None


@dataclass(frozen=True, slots=True)
class RabbitMqPublishProperties:
    """
    RabbitMQ 发布属性。
    """

    content_type: str
    delivery_mode: int
    message_id: str
    correlation_id: str
    timestamp: datetime
    headers: RabbitMqPublishHeaders

    def to_amqp_properties(self) -> RabbitMqPublishPropertyMapping:
        """
        转换为 amqpstorm 发布属性。
        """

        header_values: RabbitMqPublishHeaderMapping = {
            RABBITMQ_HEADER_REQUEST_ID: self.headers.request_id,
        }
        if self.headers.trace_id is not None:
            header_values[RABBITMQ_HEADER_TRACE_ID] = self.headers.trace_id
        return {
            "content_type": self.content_type,
            "delivery_mode": self.delivery_mode,
            "message_id": self.message_id,
            "correlation_id": self.correlation_id,
            "timestamp": self.timestamp,
            "headers": header_values,
        }


class RabbitMqMessageBus(MessageBus):
    """
    RabbitMQ 消息总线。
    """

    def __init__(self, *, detail: RabbitMqMessageBackendDetail) -> None:
        """
        初始化 RabbitMQ 消息总线。
        """

        self._detail = detail
        self._connection: UriConnection | None = None
        self._channel: Channel | None = None
        self._closed = False

    def publish(self, message: TaskMessageEnvelope) -> MessagePublishResult:
        """
        发布任务消息。
        """

        try:
            channel = self._ensure_channel()
            properties = self._build_publish_properties(message).to_amqp_properties()
            result = channel.basic.publish(
                body=self._serialize_message(message),
                routing_key=message.payload.job_kind,
                exchange=self._detail.task_exchange_name,
                properties=properties,
                mandatory=RABBITMQ_PUBLISH_MANDATORY,
            )
            self._check_publish_exceptions(channel)
            if self._detail.publisher_confirm_enabled and result is False:
                raise HttpFaultException(
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                    error_code=CoreErrorCode.TASK_FAILED,
                    message=RABBITMQ_PUBLISH_NACK_MESSAGE,
                )
            routed = self._resolve_routed(result)
            return MessagePublishResult.build_succeeded(
                message_id=message.header.message_id,
                routed=routed,
            )
        except HttpFaultException:
            raise
        except AMQPError as exc:
            raise HttpFaultException(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                error_code=CoreErrorCode.TASK_FAILED,
                message=RABBITMQ_PUBLISH_FAILED_MESSAGE,
                detail=str(exc),
            ) from exc

    def _resolve_routed(self, publish_result: object) -> bool:
        """
        解析 RabbitMQ 发布路由结果。
        """

        if self._detail.publisher_confirm_enabled:
            return publish_result is True
        return False

    def _check_publish_exceptions(self, channel: object) -> None:
        """
        检查 RabbitMQ mandatory 发布异常。
        """

        checker = getattr(channel, "check_for_exceptions", None)
        if callable(checker):
            checker()

    @property
    def backend(self) -> MessageBusBackend:
        """
        读取消息总线后端标识。
        """

        return MessageBusBackend.RABBITMQ

    def close(self) -> None:
        """
        关闭 RabbitMQ 连接。
        """

        if self._closed:
            return
        try:
            if self._channel is not None:
                self._channel.close()
            if self._connection is not None:
                self._connection.close()
        except AMQPError as exc:
            raise HttpFaultException(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                error_code=CoreErrorCode.RESOURCE_NOT_READY,
                message=RABBITMQ_CLOSE_FAILED_MESSAGE,
                detail=str(exc),
            ) from exc
        finally:
            self._closed = True
            self._channel = None
            self._connection = None

    def _ensure_channel(self) -> Channel:
        """
        确保 RabbitMQ 信道已经初始化。
        """

        if self._channel is not None:
            return self._channel
        connection_uri = RabbitMqMessageGateway(self._detail.rabbitmq_url).build_connection_uri(
            timeout_seconds=self._detail.publisher_confirm_timeout_seconds
        )
        connection = UriConnection(connection_uri)
        channel = cast(
            Channel,
            connection.channel(rpc_timeout=self._detail.publisher_confirm_timeout_seconds),
        )
        channel.exchange.declare(
            exchange=self._detail.task_exchange_name,
            exchange_type=self._detail.task_exchange_type,
            durable=self._detail.task_exchange_durable,
        )
        if self._detail.publisher_confirm_enabled:
            channel.confirm_deliveries()
        self._connection = connection
        self._channel = channel
        return channel

    def _serialize_message(self, message: TaskMessageEnvelope) -> str:
        """
        序列化任务消息。
        """

        return json.dumps(message.model_dump(mode="json"), ensure_ascii=False)

    def _build_publish_properties(
        self,
        message: TaskMessageEnvelope,
    ) -> RabbitMqPublishProperties:
        """
        构建 RabbitMQ 发布属性。
        """

        return RabbitMqPublishProperties(
            content_type=RABBITMQ_CONTENT_TYPE_JSON,
            delivery_mode=(
                RABBITMQ_DELIVERY_MODE_PERSISTENT
                if self._detail.task_message_persistent
                else RABBITMQ_DELIVERY_MODE_TRANSIENT
            ),
            message_id=message.header.message_id,
            correlation_id=message.header.request_id,
            timestamp=datetime.fromtimestamp(
                message.header.created_at_epoch,
                tz=UTC,
            ),
            headers=RabbitMqPublishHeaders(
                request_id=message.header.request_id,
                trace_id=message.header.trace_id,
            ),
        )
