"""
消息总线契约核心契约模块。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Annotated, Final, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

TASK_MESSAGE_SCHEMA_VERSION: Final = "1.0"
TASK_MESSAGE_KIND: Final = "task_message"
MESSAGE_PUBLISH_RESULT_HEADER_KIND: Final = "message_publish_result"
MESSAGE_PUBLISH_SUCCEEDED_KIND: Final = "message_publish_succeeded"
MESSAGE_PUBLISH_FAILED_KIND: Final = "message_publish_failed"
MESSAGE_ID_MINIMUM_LENGTH = 1
REQUEST_ID_MINIMUM_LENGTH = 1
TRACE_ID_MINIMUM_LENGTH = 1
LOCAL_MESSAGE_BUS_BACKEND_KIND = "local"
RABBITMQ_MESSAGE_BUS_BACKEND_KIND = "rabbitmq"
FAILURE_REASON_MINIMUM_LENGTH = 1


class MessageBusBackend(StrEnum):
    """
    消息总线后端枚举。
    """

    LOCAL = LOCAL_MESSAGE_BUS_BACKEND_KIND
    RABBITMQ = RABBITMQ_MESSAGE_BUS_BACKEND_KIND


class TaskMessageHeader(BaseModel):
    """
    任务消息头 Pydantic 模型，用于承载消息公共头信息。

    :ivar model_config: Pydantic 模型配置对象。约束：禁止额外字段。默认值：``ConfigDict(extra='forbid')``。取值语义：控制模型校验行为。
    :vartype model_config: ConfigDict
    :ivar message_id: 消息唯一标识。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于幂等、追踪和日志关联。
    :vartype message_id: str
    :ivar created_at_epoch: 消息创建时间戳。约束：需符合 ``int`` 注解。默认值：无，必须显式提供。取值语义：使用 Unix 秒级时间戳表示。
    :vartype created_at_epoch: int
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["task_message"] = TASK_MESSAGE_KIND
    schema_version: Literal["1.0"] = TASK_MESSAGE_SCHEMA_VERSION
    message_id: str = Field(min_length=MESSAGE_ID_MINIMUM_LENGTH)
    request_id: str = Field(
        default_factory=lambda: str(uuid4()),
        min_length=REQUEST_ID_MINIMUM_LENGTH,
    )
    trace_id: str | None = Field(default=None, min_length=TRACE_ID_MINIMUM_LENGTH)
    created_at_epoch: int


class TaskMessagePayload(BaseModel):
    """
    任务消息载荷 Pydantic 模型，用于承载任务调度所需业务字段。

    :ivar model_config: Pydantic 模型配置对象。约束：禁止额外字段。默认值：``ConfigDict(extra='forbid')``。取值语义：控制模型校验行为。
    :vartype model_config: ConfigDict
    :ivar kind: 结构类型标识。约束：需符合 ``str`` 注解。默认值：``TASK_MESSAGE_KIND``。取值语义：标识当前消息载荷类别。
    :vartype kind: str
    :ivar schema_version: 结构模式版本。约束：需符合 ``str`` 注解。默认值：``TASK_MESSAGE_SCHEMA_VERSION``。取值语义：标识当前载荷版本。
    :vartype schema_version: str
    :ivar job_kind: 任务类型标识。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于定位任务处理器。
    :vartype job_kind: str
    :ivar deduplication_key: 去重键。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于控制重复投递判定。
    :vartype deduplication_key: str
    :ivar retry_limit: 重试次数上限。约束：需符合 ``int`` 注解。默认值：无，必须显式提供。取值语义：定义任务失败后的最大重试次数。
    :vartype retry_limit: int
    :ivar payload_kind: 业务载荷类型。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：辅助处理器反序列化具体业务模型。
    :vartype payload_kind: str
    :ivar payload_json: 业务载荷 JSON 文本。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：保存实际任务参数。
    :vartype payload_json: str
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["task_message"] = TASK_MESSAGE_KIND
    schema_version: Literal["1.0"] = TASK_MESSAGE_SCHEMA_VERSION
    job_kind: str
    deduplication_key: str
    retry_limit: int
    payload_kind: str
    payload_json: str


class TaskMessageEnvelope(BaseModel):
    """
    任务消息信封 Pydantic 模型，用于聚合消息头与业务载荷。

    :ivar model_config: Pydantic 模型配置对象。约束：禁止额外字段。默认值：``ConfigDict(extra='forbid')``。取值语义：控制模型校验行为。
    :vartype model_config: ConfigDict
    :ivar header: 消息头对象。约束：需符合 ``TaskMessageHeader`` 注解。默认值：无，必须显式提供。取值语义：保存追踪与创建时间信息。
    :vartype header: TaskMessageHeader
    :ivar payload: 业务载荷对象。约束：需符合 ``TaskMessagePayload`` 注解。默认值：无，必须显式提供。取值语义：保存任务调度参数。
    :vartype payload: TaskMessagePayload
    """

    model_config = ConfigDict(extra="forbid")

    header: TaskMessageHeader
    payload: TaskMessagePayload

    @model_validator(mode="after")
    def validate_message_contract(self) -> TaskMessageEnvelope:
        """
        校验消息信封头与载荷一致性。
        """

        if self.header.kind != self.payload.kind:
            raise ValueError("任务消息 header.kind 必须与 payload.kind 一致。")
        if self.header.schema_version != self.payload.schema_version:
            raise ValueError("任务消息 header.schema_version 必须与 payload.schema_version 一致。")
        return self


class MessagePublishResultHeader(BaseModel):
    """
    消息发布结果公共头。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["message_publish_result"] = MESSAGE_PUBLISH_RESULT_HEADER_KIND
    schema_version: Literal["1.0"] = TASK_MESSAGE_SCHEMA_VERSION
    message_id: str = Field(min_length=MESSAGE_ID_MINIMUM_LENGTH)


class MessagePublishSucceededDetail(BaseModel):
    """
    消息发布成功扩展字段。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["message_publish_succeeded"] = MESSAGE_PUBLISH_SUCCEEDED_KIND
    schema_version: Literal["1.0"] = TASK_MESSAGE_SCHEMA_VERSION
    published: bool = True
    routed: bool


class MessagePublishFailedDetail(BaseModel):
    """
    消息发布失败扩展字段。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["message_publish_failed"] = MESSAGE_PUBLISH_FAILED_KIND
    schema_version: Literal["1.0"] = TASK_MESSAGE_SCHEMA_VERSION
    published: bool = False
    routed: bool = False
    failure_reason: str = Field(min_length=FAILURE_REASON_MINIMUM_LENGTH)


MessagePublishResultDetailUnion = Annotated[
    MessagePublishSucceededDetail | MessagePublishFailedDetail,
    Field(discriminator="kind"),
]


class MessagePublishResult(BaseModel):
    """
    消息发布结果信封。
    """

    model_config = ConfigDict(extra="forbid")

    header: MessagePublishResultHeader
    detail: MessagePublishResultDetailUnion

    @property
    def published(self) -> bool:
        """
        读取发布结果。
        """

        return self.detail.published

    @property
    def routed(self) -> bool:
        """
        读取路由结果。
        """

        return self.detail.routed

    @property
    def message_id(self) -> str:
        """
        读取消息标识。
        """

        return self.header.message_id

    @property
    def failure_reason(self) -> str | None:
        """
        读取失败原因。
        """

        if isinstance(self.detail, MessagePublishFailedDetail):
            return self.detail.failure_reason
        return None

    @classmethod
    def build_succeeded(cls, *, message_id: str, routed: bool) -> MessagePublishResult:
        """
        构建消息发布成功信封。
        """

        return cls(
            header=MessagePublishResultHeader(message_id=message_id),
            detail=MessagePublishSucceededDetail(routed=routed),
        )

    @classmethod
    def build_failed(
        cls,
        *,
        message_id: str,
        failure_reason: str,
    ) -> MessagePublishResult:
        """
        构建消息发布失败信封。
        """

        return cls(
            header=MessagePublishResultHeader(message_id=message_id),
            detail=MessagePublishFailedDetail(failure_reason=failure_reason),
        )


class TaskMessagePublishExtraParams(BaseModel):
    """
    任务消息发布额外参数。
    """

    model_config = ConfigDict(extra="forbid")

    routing_key_for_publish: str


class TaskMessagePublishExtra(BaseModel):
    """
    任务消息发布扩展参数。
    """

    model_config = ConfigDict(extra="forbid")

    other_extra_params: TaskMessagePublishExtraParams
    task_id: str = Field(min_length=MESSAGE_ID_MINIMUM_LENGTH)
    max_retry_times: int = Field(ge=0)


class FunboostMessageBody(BaseModel):
    """
    Funboost 消息体。
    """

    model_config = ConfigDict(extra="forbid")

    task_message: TaskMessageEnvelope


class MessageBus(ABC):
    """
    消息总线抽象基类，定义任务消息发布能力。
    """

    @abstractmethod
    def publish(self, message: TaskMessageEnvelope) -> MessagePublishResult:
        """
        发布任务消息。

        :param message: 任务消息信封对象。约束：需符合 ``TaskMessageEnvelope`` 注解。
        :type message: TaskMessageEnvelope
        :returns: 消息发布结果。
        :rtype: MessagePublishResult
        """

        pass

    @property
    @abstractmethod
    def backend(self) -> MessageBusBackend:
        """
        读取消息总线真实后端标识。

        :returns: 消息总线后端。
        :rtype: MessageBusBackend
        """

        pass

    @abstractmethod
    def close(self) -> None:
        """
        关闭消息总线持有的外部资源。

        :returns: 无返回值。
        :rtype: None
        """

        pass
