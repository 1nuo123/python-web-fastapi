"""流操作绑定与非流式交付契约。"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Final, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.core.stream_contract.stream_event_contract import (
    STREAM_SCHEMA_VERSION,
    StreamCloseReason,
    StreamEventEnvelope,
    StreamTransport,
)

STREAM_OPERATION_BINDING_ENVELOPE_KIND: Final = "stream_operation_binding_envelope"
STREAM_BATCH_ENVELOPE_KIND: Final = "stream_batch_envelope"
STREAM_BATCH_HEADER_KIND: Final = "stream_batch_header"
STREAM_BATCH_COMPLETED_KIND: Final = "stream_batch_completed"
STREAM_BATCH_REJECTED_KIND: Final = "stream_batch_rejected"
COMMAND_STREAM_BINDING_KIND: Final[Literal["command_stream_binding"]] = "command_stream_binding"
SUBSCRIPTION_STREAM_BINDING_KIND: Final[Literal["subscription_stream_binding"]] = (
    "subscription_stream_binding"
)
SSE_DELIVERY_KIND: Final[Literal["sse_delivery"]] = "sse_delivery"
STREAM_BINDING_TEXT_MINIMUM_LENGTH = 1
STREAM_COLLECTION_MINIMUM = 1


class StreamDeliveryKind(StrEnum):
    """流操作绑定类型。"""

    COMMAND = COMMAND_STREAM_BINDING_KIND
    SUBSCRIPTION = SUBSCRIPTION_STREAM_BINDING_KIND


class SseDeliveryMode(StrEnum):
    """SSE 浏览器交付模式。"""

    BEARER_POST = "bearer_post"
    TICKET_GET = "ticket_get"
    DUAL = "dual"


class SseDeliveryDetail(BaseModel):
    """SSE 交付扩展。"""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["sse_delivery"] = SSE_DELIVERY_KIND
    schema_version: Literal["1.0"] = STREAM_SCHEMA_VERSION
    mode: SseDeliveryMode
    heartbeat_seconds: int = Field(ge=STREAM_COLLECTION_MINIMUM)
    retry_milliseconds: int = Field(ge=STREAM_COLLECTION_MINIMUM)
    resume_enabled: bool
    ticket_required: bool

    @model_validator(mode="after")
    def validate_ticket_mode(self) -> SseDeliveryDetail:
        """校验 native EventSource 与单次票据声明一致。"""

        native_enabled = self.mode in {SseDeliveryMode.TICKET_GET, SseDeliveryMode.DUAL}
        if native_enabled != self.ticket_required:
            raise ValueError("native EventSource 交付与单次票据声明必须一致。")
        return self


class StreamOperationBindingHeader(BaseModel):
    """流操作绑定公共头。"""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["stream_operation_binding_envelope"] = STREAM_OPERATION_BINDING_ENVELOPE_KIND
    schema_version: Literal["1.0"] = STREAM_SCHEMA_VERSION
    operation_name: str = Field(min_length=STREAM_BINDING_TEXT_MINIMUM_LENGTH)
    delivery_kind: StreamDeliveryKind


class StreamBindingDetailBase(BaseModel):
    """流操作绑定扩展公共字段。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = STREAM_SCHEMA_VERSION
    batch_path: str = Field(min_length=STREAM_BINDING_TEXT_MINIMUM_LENGTH)
    sse_path: str | None = None
    sse_delivery: SseDeliveryDetail | None
    websocket_path: str | None = None
    ticket_path: str | None = None
    websocket_ticket_required: bool
    transports: frozenset[StreamTransport]
    resumable: bool

    @model_validator(mode="after")
    def validate_transports(self) -> StreamBindingDetailBase:
        """校验命令流必须提供非流式 HTTP 交付。

        :returns: 已校验绑定扩展。
        :rtype: CommandStreamBindingDetail
        :raises ValueError: 传输声明与路径不一致时抛出。
        """

        if StreamTransport.HTTP not in self.transports:
            raise ValueError("流操作必须声明非流式 HTTP 交付。")
        if StreamTransport.SSE in self.transports and self.sse_path is None:
            raise ValueError("声明 SSE 交付时必须配置 sse_path。")
        if StreamTransport.SSE in self.transports and self.sse_delivery is None:
            raise ValueError("声明 SSE 交付时必须配置 sse_delivery。")
        if StreamTransport.SSE not in self.transports and self.sse_delivery is not None:
            raise ValueError("未声明 SSE 交付时不得配置 sse_delivery。")
        if StreamTransport.SSE not in self.transports and self.sse_path is not None:
            raise ValueError("未声明 SSE 交付时不得配置 sse_path。")
        if StreamTransport.WEBSOCKET in self.transports and self.websocket_path is None:
            raise ValueError("声明 WebSocket 交付时必须配置 websocket_path。")
        if StreamTransport.WEBSOCKET not in self.transports and self.websocket_path is not None:
            raise ValueError("未声明 WebSocket 交付时不得配置 websocket_path。")
        if self.websocket_ticket_required:
            if StreamTransport.WEBSOCKET not in self.transports:
                raise ValueError("要求 WebSocket 票据时必须声明 WebSocket 交付。")
            if self.ticket_path is None:
                raise ValueError("要求 WebSocket 票据时必须配置 ticket_path。")
        if self.ticket_path is not None and not (
            self.websocket_ticket_required
            or (self.sse_delivery is not None and self.sse_delivery.ticket_required)
        ):
            raise ValueError("未声明票据交付时不得配置 ticket_path。")
        if self.resumable and StreamTransport.SSE in self.transports:
            if self.sse_delivery is None or not self.sse_delivery.resume_enabled:
                raise ValueError("可恢复 SSE 操作必须启用 SSE 恢复声明。")
        return self


class CommandStreamBindingDetail(StreamBindingDetailBase):
    """命令型流操作扩展。"""

    kind: Literal["command_stream_binding"] = COMMAND_STREAM_BINDING_KIND


class SubscriptionStreamBindingDetail(StreamBindingDetailBase):
    """订阅型流操作扩展。"""

    kind: Literal["subscription_stream_binding"] = SUBSCRIPTION_STREAM_BINDING_KIND


StreamOperationBindingDetail = Annotated[
    CommandStreamBindingDetail | SubscriptionStreamBindingDetail,
    Field(discriminator="kind"),
]


class StreamOperationBindingEnvelope(BaseModel):
    """流操作绑定信封。"""

    model_config = ConfigDict(extra="forbid")

    envelope_kind: Literal["stream_operation_binding_envelope"] = (
        STREAM_OPERATION_BINDING_ENVELOPE_KIND
    )
    schema_version: Literal["1.0"] = STREAM_SCHEMA_VERSION
    header: StreamOperationBindingHeader
    detail: StreamOperationBindingDetail

    @model_validator(mode="after")
    def validate_contract(self) -> StreamOperationBindingEnvelope:
        """校验绑定头与扩展类型、版本一致。

        :returns: 已校验绑定信封。
        :rtype: StreamOperationBindingEnvelope
        :raises ValueError: 类型或版本不一致时抛出。
        """

        if self.header.delivery_kind != self.detail.kind:
            raise ValueError("流操作绑定公共头类型必须与扩展字段类型一致。")
        if self.schema_version != self.header.schema_version:
            raise ValueError("流操作绑定信封与公共头 schema_version 必须一致。")
        if self.schema_version != self.detail.schema_version:
            raise ValueError("流操作绑定 schema_version 必须一致。")
        return self


class StreamCollectionLimit(BaseModel):
    """非流式聚合三重限制。"""

    model_config = ConfigDict(extra="forbid")

    max_events: int = Field(ge=STREAM_COLLECTION_MINIMUM)
    max_bytes: int = Field(ge=STREAM_COLLECTION_MINIMUM)
    timeout_seconds: float = Field(gt=0)


T_BatchDetail = TypeVar("T_BatchDetail", bound=BaseModel)


class SseEventMapping(BaseModel):
    """单个统一流事件的 SSE 映射结果。"""

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=STREAM_BINDING_TEXT_MINIMUM_LENGTH)
    event_kind: str = Field(min_length=STREAM_BINDING_TEXT_MINIMUM_LENGTH)
    data_json: str = Field(min_length=STREAM_BINDING_TEXT_MINIMUM_LENGTH)
    retry_milliseconds: int = Field(ge=STREAM_COLLECTION_MINIMUM)


class SseResumeRequest(BaseModel):
    """SSE 响应启动前完成校验的恢复请求。"""

    model_config = ConfigDict(extra="forbid")

    stream_id: str = Field(min_length=STREAM_BINDING_TEXT_MINIMUM_LENGTH)
    last_event_id: str = Field(min_length=STREAM_BINDING_TEXT_MINIMUM_LENGTH)


class StreamBatchResultKind(StrEnum):
    """非流式聚合结果类型。"""

    COMPLETED = STREAM_BATCH_COMPLETED_KIND
    REJECTED = STREAM_BATCH_REJECTED_KIND


class StreamBatchHeader(BaseModel):
    """非流式聚合结果公共头。"""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["stream_batch_header"] = STREAM_BATCH_HEADER_KIND
    schema_version: Literal["1.0"] = STREAM_SCHEMA_VERSION
    stream_id: str = Field(min_length=STREAM_BINDING_TEXT_MINIMUM_LENGTH)
    result_kind: StreamBatchResultKind


class StreamBatchCompletedDetail(BaseModel, Generic[T_BatchDetail]):
    """非流式聚合正常完成扩展。"""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["stream_batch_completed"] = STREAM_BATCH_COMPLETED_KIND
    schema_version: Literal["1.0"] = STREAM_SCHEMA_VERSION
    events: list[StreamEventEnvelope[T_BatchDetail]]
    last_sequence: int = Field(ge=0)
    event_count: int = Field(ge=0)
    total_bytes: int = Field(ge=0)
    terminal_event_id: str = Field(min_length=STREAM_BINDING_TEXT_MINIMUM_LENGTH)

    @model_validator(mode="after")
    def validate_summary(self) -> StreamBatchCompletedDetail[T_BatchDetail]:
        """校验完成摘要与事件集合一致。"""

        if not self.events:
            raise ValueError("完成的非流式聚合结果必须包含事件。")
        terminal = self.events[-1]
        if self.event_count != len(self.events):
            raise ValueError("非流式聚合事件数摘要不一致。")
        if self.last_sequence != terminal.header.sequence:
            raise ValueError("非流式聚合末序号摘要不一致。")
        if self.terminal_event_id != terminal.header.event_id:
            raise ValueError("非流式聚合终止事件标识不一致。")
        if terminal.header.event_kind != "stream_completed":
            raise ValueError("完成的非流式聚合结果必须以 stream_completed 终止。")
        stream_ids = {event.header.stream_id for event in self.events}
        if len(stream_ids) != STREAM_COLLECTION_MINIMUM:
            raise ValueError("非流式聚合结果不得混合多个 stream_id。")
        expected_sequences = list(range(len(self.events)))
        actual_sequences = [event.header.sequence for event in self.events]
        if actual_sequences != expected_sequences:
            raise ValueError("非流式聚合事件 sequence 必须连续递增。")
        return self


class StreamBatchRejectedDetail(BaseModel):
    """非流式聚合拒绝扩展。"""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["stream_batch_rejected"] = STREAM_BATCH_REJECTED_KIND
    schema_version: Literal["1.0"] = STREAM_SCHEMA_VERSION
    error_code: str = Field(min_length=STREAM_BINDING_TEXT_MINIMUM_LENGTH)
    message: str = Field(min_length=STREAM_BINDING_TEXT_MINIMUM_LENGTH)
    retryable: bool
    close_reason: StreamCloseReason
    last_sequence: int = Field(ge=0)
    event_count: int = Field(ge=0)
    total_bytes: int = Field(ge=0)
    terminal_event_id: str = Field(min_length=STREAM_BINDING_TEXT_MINIMUM_LENGTH)


class StreamBatchEnvelope(BaseModel, Generic[T_BatchDetail]):
    """非流式聚合结果。"""

    model_config = ConfigDict(extra="forbid")

    envelope_kind: Literal["stream_batch_envelope"] = STREAM_BATCH_ENVELOPE_KIND
    schema_version: Literal["1.0"] = STREAM_SCHEMA_VERSION
    header: StreamBatchHeader
    detail: StreamBatchCompletedDetail[T_BatchDetail] | StreamBatchRejectedDetail = Field(
        discriminator="kind"
    )

    @model_validator(mode="after")
    def validate_contract(self) -> StreamBatchEnvelope[T_BatchDetail]:
        """校验聚合信封的类型、版本、流标识和终止摘要。"""

        if self.header.result_kind != self.detail.kind:
            raise ValueError("非流式聚合公共头类型必须与扩展字段类型一致。")
        if self.schema_version != self.header.schema_version:
            raise ValueError("非流式聚合信封与公共头 schema_version 必须一致。")
        if self.schema_version != self.detail.schema_version:
            raise ValueError("非流式聚合信封与扩展 schema_version 必须一致。")
        if isinstance(self.detail, StreamBatchCompletedDetail):
            if self.header.stream_id != self.detail.events[0].header.stream_id:
                raise ValueError("非流式聚合 stream_id 摘要不一致。")
        return self
