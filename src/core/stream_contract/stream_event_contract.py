"""流事件公共契约。

该模块冻结协议无关的事件头、基础生命周期事件和泛型事件信封。
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Final, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

STREAM_SCHEMA_VERSION: Final = "1.0"
STREAM_EVENT_ENVELOPE_KIND: Final = "stream_event_envelope"
STREAM_STARTED_KIND: Final = "stream_started"
STREAM_PROGRESS_KIND: Final = "stream_progress"
STREAM_HEARTBEAT_KIND: Final = "stream_heartbeat"
STREAM_COMPLETED_KIND: Final = "stream_completed"
STREAM_FAULT_KIND: Final = "stream_fault"
STREAM_IDENTIFIER_MINIMUM_LENGTH = 1
STREAM_SEQUENCE_MINIMUM = 0
STREAM_PROGRESS_MINIMUM = 0


class StreamTransport(StrEnum):
    """流交付传输类型。"""

    HTTP = "http"
    SSE = "sse"
    WEBSOCKET = "websocket"


class StreamCloseReason(StrEnum):
    """流关闭原因封闭集合。"""

    COMPLETED = "completed"
    CLIENT_CANCELLED = "client_cancelled"
    CLIENT_DISCONNECTED = "client_disconnected"
    TIMEOUT = "timeout"
    SLOW_CONSUMER = "slow_consumer"
    POLICY_REJECTED = "policy_rejected"
    SERVICE_SHUTDOWN = "service_shutdown"
    INTERNAL_ERROR = "internal_error"


class StreamEventHeader(BaseModel):
    """流事件公共头。

    :ivar stream_id: 流会话标识。
    :ivar event_id: 事件标识。
    :ivar sequence: 会话内单调递增序号。
    :ivar event_kind: 扩展事件类型。
    :ivar schema_version: 契约版本。
    :ivar request_id: 请求标识。
    :ivar trace_id: 链路标识。
    :ivar emitted_at: 事件发出时间。
    """

    model_config = ConfigDict(extra="forbid")

    stream_id: str = Field(min_length=STREAM_IDENTIFIER_MINIMUM_LENGTH)
    event_id: str = Field(min_length=STREAM_IDENTIFIER_MINIMUM_LENGTH)
    sequence: int = Field(ge=STREAM_SEQUENCE_MINIMUM)
    event_kind: str = Field(min_length=STREAM_IDENTIFIER_MINIMUM_LENGTH)
    schema_version: Literal["1.0"] = STREAM_SCHEMA_VERSION
    request_id: str = Field(min_length=STREAM_IDENTIFIER_MINIMUM_LENGTH)
    trace_id: str | None
    emitted_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class StreamStartedDetail(BaseModel):
    """流开始事件扩展。"""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["stream_started"] = STREAM_STARTED_KIND
    schema_version: Literal["1.0"] = STREAM_SCHEMA_VERSION
    operation_name: str = Field(min_length=STREAM_IDENTIFIER_MINIMUM_LENGTH)
    transport: StreamTransport
    resumable: bool


class StreamProgressDetail(BaseModel):
    """流进度事件扩展。"""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["stream_progress"] = STREAM_PROGRESS_KIND
    schema_version: Literal["1.0"] = STREAM_SCHEMA_VERSION
    current: int = Field(ge=STREAM_PROGRESS_MINIMUM)
    total: int | None = Field(default=None, ge=STREAM_PROGRESS_MINIMUM)
    stage: str = Field(min_length=STREAM_IDENTIFIER_MINIMUM_LENGTH)

    @model_validator(mode="after")
    def validate_progress(self) -> StreamProgressDetail:
        """校验当前进度不超过已声明总量。

        :returns: 已校验的进度事件。
        :rtype: StreamProgressDetail
        :raises ValueError: 当前进度超过总量时抛出。
        """

        if self.total is not None and self.current > self.total:
            raise ValueError("流进度 current 不得超过 total。")
        return self


class StreamHeartbeatDetail(BaseModel):
    """流业务心跳事件扩展。

    SSE 协议注释心跳不使用该事件，避免污染业务序列。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["stream_heartbeat"] = STREAM_HEARTBEAT_KIND
    schema_version: Literal["1.0"] = STREAM_SCHEMA_VERSION


class StreamCompletedDetail(BaseModel):
    """流正常完成事件扩展。"""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["stream_completed"] = STREAM_COMPLETED_KIND
    schema_version: Literal["1.0"] = STREAM_SCHEMA_VERSION
    last_sequence: int = Field(ge=STREAM_SEQUENCE_MINIMUM)
    event_count: int = Field(ge=STREAM_SEQUENCE_MINIMUM)


class StreamFaultDetail(BaseModel):
    """流故障终止事件扩展。"""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["stream_fault"] = STREAM_FAULT_KIND
    schema_version: Literal["1.0"] = STREAM_SCHEMA_VERSION
    error_code: str = Field(min_length=STREAM_IDENTIFIER_MINIMUM_LENGTH)
    message: str = Field(min_length=STREAM_IDENTIFIER_MINIMUM_LENGTH)
    retryable: bool
    close_reason: StreamCloseReason


StreamLifecycleDetail = Annotated[
    StreamStartedDetail
    | StreamProgressDetail
    | StreamHeartbeatDetail
    | StreamCompletedDetail
    | StreamFaultDetail,
    Field(discriminator="kind"),
]

T_StreamDetail = TypeVar("T_StreamDetail", bound=BaseModel)


class StreamEventEnvelope(BaseModel, Generic[T_StreamDetail]):
    """流事件泛型信封。

    :ivar header: 流事件公共头。
    :ivar detail: 业务声明的强类型扩展字段。
    """

    model_config = ConfigDict(extra="forbid")

    envelope_kind: Literal["stream_event_envelope"] = STREAM_EVENT_ENVELOPE_KIND
    schema_version: Literal["1.0"] = STREAM_SCHEMA_VERSION
    header: StreamEventHeader
    detail: T_StreamDetail

    @model_validator(mode="after")
    def validate_contract(self) -> StreamEventEnvelope[T_StreamDetail]:
        """校验公共头与扩展字段类型、版本一致。

        :returns: 已校验的流事件信封。
        :rtype: StreamEventEnvelope[T_StreamDetail]
        :raises ValueError: 类型或版本不一致时抛出。
        """

        detail_kind = getattr(self.detail, "kind", None)
        detail_schema_version = getattr(self.detail, "schema_version", None)
        if self.header.event_kind != detail_kind:
            raise ValueError("流事件公共头类型必须与扩展字段类型一致。")
        if self.schema_version != self.header.schema_version:
            raise ValueError("流事件信封与公共头 schema_version 必须一致。")
        if self.schema_version != detail_schema_version:
            raise ValueError("流事件 schema_version 必须一致。")
        return self


class StreamSequenceValidator:
    """流事件序列校验器。"""

    def __init__(self) -> None:
        """初始化序列校验状态。"""

        self._last_sequence: int | None = None

    def accept(self, event: StreamEventEnvelope[BaseModel]) -> None:
        """接收并校验下一个事件。

        :param event: 待校验事件。
        :type event: StreamEventEnvelope[BaseModel]
        :raises ValueError: 序列未严格递增时抛出。
        """

        expected = (
            STREAM_SEQUENCE_MINIMUM if self._last_sequence is None else self._last_sequence + 1
        )
        if event.header.sequence != expected:
            raise ValueError("流事件 sequence 必须从零开始并严格单调递增。")
        self._last_sequence = event.header.sequence
