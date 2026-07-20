"""
任务运行时契约核心模块。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

TASK_RUNTIME_SCHEMA_VERSION: Final = "1.0"
MESSAGE_RUNTIME_SCHEMA_VERSION: Final = TASK_RUNTIME_SCHEMA_VERSION
LOCAL_TASK_BACKEND_KIND: Final = "local"
FUNBOOST_TASK_BACKEND_KIND: Final = "funboost"
LOCAL_MESSAGE_BACKEND_KIND: Final = "local"
RABBITMQ_MESSAGE_BACKEND_KIND: Final = "rabbitmq"
LOCAL_INLINE_TASK_RUNTIME_MODE = "local_inline"
LOCAL_QUEUED_TASK_RUNTIME_MODE = "local_queued"
FUNBOOST_PRODUCER_TASK_RUNTIME_MODE = "funboost_producer"
FUNBOOST_CONSUMER_TASK_RUNTIME_MODE = "funboost_consumer"
FUNBOOST_RABBITMQ_AMQPSTORM_BROKER_KIND = "RABBITMQ_AMQPSTORM"
FUNBOOST_RABBITMQ_AMQP_BROKER_KIND = "RABBITMQ_AMQP"
FUNBOOST_RABBITMQ_COMPLEX_ROUTING_BROKER_KIND = "RABBITMQ_COMPLEX_ROUTING"
AMQP_URL_PREFIX = "amqp://"
AMQPS_URL_PREFIX = "amqps://"
SCHEMA_VERSION_FIELD_NAME = "schema_version"
KIND_FIELD_NAME = "kind"
BROKER_KIND_FIELD_NAME = "broker_kind"
QUEUE_NAME_MINIMUM_LENGTH = 1
EXCHANGE_NAME_MINIMUM_LENGTH = 1
ROUTING_KEY_MINIMUM_LENGTH = 1
PREFETCH_COUNT_MINIMUM = 1
WORKER_COUNT_MINIMUM = 1
RETRY_LIMIT_MINIMUM = 0
PROBE_TIMEOUT_SECONDS_MINIMUM = 1
PUBLISH_CONFIRM_TIMEOUT_SECONDS_MINIMUM = 1
EXTERNAL_QUEUE_MAX_LENGTH_MINIMUM = 1
EXTERNAL_QUEUE_PREFETCH_COUNT_MINIMUM = 1
DEFAULT_EXTERNAL_QUEUE_MAX_LENGTH = 10000
DEFAULT_EXTERNAL_QUEUE_PREFETCH_COUNT = 8
DEFAULT_DEAD_LETTER_EXCHANGE_NAME = "task.dead_letter"
LOCAL_MESSAGE_MAX_ITEMS_MINIMUM = 1
LOCAL_MESSAGE_MAX_ITEMS_DEFAULT = 1000
RETRY_DELAY_SECONDS_MINIMUM = 0
RETRY_BACKOFF_MULTIPLIER_MINIMUM = 1
RETRY_MAX_DELAY_SECONDS_MINIMUM = 0
DEFAULT_RETRY_DELAY_SECONDS = 1
DEFAULT_RETRY_BACKOFF_MULTIPLIER = 2
DEFAULT_RETRY_MAX_DELAY_SECONDS = 30


class MessageBackend(StrEnum):
    """
    消息后端枚举。
    """

    LOCAL = LOCAL_MESSAGE_BACKEND_KIND
    RABBITMQ = RABBITMQ_MESSAGE_BACKEND_KIND


class TaskBackend(StrEnum):
    """
    任务后端枚举。
    """

    LOCAL = LOCAL_TASK_BACKEND_KIND
    FUNBOOST = FUNBOOST_TASK_BACKEND_KIND


class TaskRuntimeMode(StrEnum):
    """
    任务运行时节点模式枚举。
    """

    LOCAL_INLINE = LOCAL_INLINE_TASK_RUNTIME_MODE
    LOCAL_QUEUED = LOCAL_QUEUED_TASK_RUNTIME_MODE
    FUNBOOST_PRODUCER = FUNBOOST_PRODUCER_TASK_RUNTIME_MODE
    FUNBOOST_CONSUMER = FUNBOOST_CONSUMER_TASK_RUNTIME_MODE


class FunboostBrokerKind(StrEnum):
    """
    Funboost Broker 枚举。
    """

    RABBITMQ_AMQPSTORM = FUNBOOST_RABBITMQ_AMQPSTORM_BROKER_KIND
    RABBITMQ_AMQP = FUNBOOST_RABBITMQ_AMQP_BROKER_KIND
    RABBITMQ_COMPLEX_ROUTING = FUNBOOST_RABBITMQ_COMPLEX_ROUTING_BROKER_KIND


class LocalMessageBackendDetail(BaseModel):
    """
    本地消息后端扩展配置。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["local"] = LOCAL_MESSAGE_BACKEND_KIND
    schema_version: Literal["1.0"] = MESSAGE_RUNTIME_SCHEMA_VERSION
    max_items: int = Field(
        default=LOCAL_MESSAGE_MAX_ITEMS_DEFAULT,
        ge=LOCAL_MESSAGE_MAX_ITEMS_MINIMUM,
    )


class RabbitMqMessageBackendDetail(BaseModel):
    """
    RabbitMQ 消息后端扩展配置。

    ``rabbitmq_url``、启动探测、交换机、消息持久化、发布确认、有界队列、预取和
    死信字段由独立消息总线与 Funboost 主链共同消费。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["rabbitmq"] = RABBITMQ_MESSAGE_BACKEND_KIND
    schema_version: Literal["1.0"] = MESSAGE_RUNTIME_SCHEMA_VERSION
    rabbitmq_url: str = Field(min_length=QUEUE_NAME_MINIMUM_LENGTH)
    startup_probe_enabled: bool
    startup_probe_timeout_seconds: int = Field(ge=PROBE_TIMEOUT_SECONDS_MINIMUM)
    task_exchange_name: str = Field(min_length=EXCHANGE_NAME_MINIMUM_LENGTH)
    task_exchange_type: str = Field(min_length=EXCHANGE_NAME_MINIMUM_LENGTH)
    task_exchange_durable: bool
    task_message_persistent: bool
    publisher_confirm_enabled: bool
    publisher_confirm_timeout_seconds: int = Field(ge=PUBLISH_CONFIRM_TIMEOUT_SECONDS_MINIMUM)
    queue_max_length: int = Field(
        default=DEFAULT_EXTERNAL_QUEUE_MAX_LENGTH,
        ge=EXTERNAL_QUEUE_MAX_LENGTH_MINIMUM,
    )
    consumer_prefetch_count: int = Field(
        default=DEFAULT_EXTERNAL_QUEUE_PREFETCH_COUNT,
        ge=EXTERNAL_QUEUE_PREFETCH_COUNT_MINIMUM,
    )
    dead_letter_exchange_name: str = Field(
        default=DEFAULT_DEAD_LETTER_EXCHANGE_NAME,
        min_length=EXCHANGE_NAME_MINIMUM_LENGTH,
    )

    @model_validator(mode="after")
    def validate_rabbitmq_url(self) -> RabbitMqMessageBackendDetail:
        """
        校验 RabbitMQ 连接地址前缀。
        :returns: 当前模型实例。
        :rtype: RabbitMqMessageBackendDetail
        :raises ValueError: 当地址前缀不合法时抛出。
        """

        if not self.rabbitmq_url.startswith((AMQP_URL_PREFIX, AMQPS_URL_PREFIX)):
            raise ValueError("RabbitMQ 连接地址必须以 amqp:// 或 amqps:// 开头。")
        return self


MessageBackendDetailUnion = Annotated[
    LocalMessageBackendDetail | RabbitMqMessageBackendDetail,
    Field(discriminator=KIND_FIELD_NAME),
]


class LocalTaskBackendDetail(BaseModel):
    """
    本地任务后端扩展配置。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["local"] = LOCAL_TASK_BACKEND_KIND
    schema_version: Literal["1.0"] = TASK_RUNTIME_SCHEMA_VERSION
    inline_execute_enabled: bool = True
    retry_delay_seconds: int = Field(
        default=DEFAULT_RETRY_DELAY_SECONDS, ge=RETRY_DELAY_SECONDS_MINIMUM
    )
    retry_backoff_multiplier: int = Field(
        default=DEFAULT_RETRY_BACKOFF_MULTIPLIER,
        ge=RETRY_BACKOFF_MULTIPLIER_MINIMUM,
    )
    retry_max_delay_seconds: int = Field(
        default=DEFAULT_RETRY_MAX_DELAY_SECONDS,
        ge=RETRY_MAX_DELAY_SECONDS_MINIMUM,
    )


class FunboostTaskBackendDetail(BaseModel):
    """
    Funboost 任务后端扩展配置。

    ``broker_kind`` 用于校验运行时与任务注册的 Broker 类型一致；重试退避字段
    直接驱动任务运行时。消费者并发和重试次数由任务注册契约控制。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["funboost"] = FUNBOOST_TASK_BACKEND_KIND
    schema_version: Literal["1.0"] = TASK_RUNTIME_SCHEMA_VERSION
    broker_kind: FunboostBrokerKind
    retry_delay_seconds: int = Field(
        default=DEFAULT_RETRY_DELAY_SECONDS, ge=RETRY_DELAY_SECONDS_MINIMUM
    )
    retry_backoff_multiplier: int = Field(
        default=DEFAULT_RETRY_BACKOFF_MULTIPLIER,
        ge=RETRY_BACKOFF_MULTIPLIER_MINIMUM,
    )
    retry_max_delay_seconds: int = Field(
        default=DEFAULT_RETRY_MAX_DELAY_SECONDS,
        ge=RETRY_MAX_DELAY_SECONDS_MINIMUM,
    )

    @model_validator(mode="after")
    def validate_funboost_task_backend_contract(self) -> FunboostTaskBackendDetail:
        """
        校验 Funboost 运行时配置。
        """

        if self.broker_kind != FunboostBrokerKind.RABBITMQ_COMPLEX_ROUTING:
            raise ValueError(
                "runtime.task.backend_detail.broker_kind 必须为 RABBITMQ_COMPLEX_ROUTING。"
            )
        return self


TaskBackendDetailUnion = Annotated[
    LocalTaskBackendDetail | FunboostTaskBackendDetail,
    Field(discriminator=KIND_FIELD_NAME),
]


class MessageRuntimeSettingsContract(BaseModel):
    """
    消息运行时契约模型。
    """

    model_config = ConfigDict(extra="forbid")

    backend: MessageBackend
    backend_detail: MessageBackendDetailUnion

    @model_validator(mode="after")
    def validate_backend_detail(self) -> MessageRuntimeSettingsContract:
        """
        校验外层后端与内层扩展字段一致。
        :returns: 当前模型实例。
        :rtype: MessageRuntimeSettingsContract
        :raises ValueError: 当外层与内层不一致时抛出。
        """

        if self.backend.value != self.backend_detail.kind:
            raise ValueError(
                "runtime.message.backend 必须与 runtime.message.backend_detail.kind 一致。"
            )
        if self.backend_detail.schema_version != MESSAGE_RUNTIME_SCHEMA_VERSION:
            raise ValueError("runtime.message.backend_detail.schema_version 必须为当前支持版本。")
        return self


class TaskRuntimeSettingsContract(BaseModel):
    """
    任务运行时契约模型。
    """

    model_config = ConfigDict(extra="forbid")

    backend: TaskBackend
    worker_enabled: bool
    backend_detail: TaskBackendDetailUnion

    @model_validator(mode="after")
    def validate_backend_detail(self) -> TaskRuntimeSettingsContract:
        """
        校验外层后端与内层扩展字段一致。
        :returns: 当前模型实例。
        :rtype: TaskRuntimeSettingsContract
        :raises ValueError: 当外层与内层不一致时抛出。
        """

        if self.backend.value != self.backend_detail.kind:
            raise ValueError("runtime.task.backend 必须与 runtime.task.backend_detail.kind 一致。")
        if self.backend_detail.schema_version != TASK_RUNTIME_SCHEMA_VERSION:
            raise ValueError("runtime.task.backend_detail.schema_version 必须为当前支持版本。")
        return self
