"""统一流式运行时契约。"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.core.stream_contract.stream_event_contract import STREAM_SCHEMA_VERSION

STREAM_RUNTIME_ENVELOPE_KIND: Final = "stream_runtime_envelope"
STREAM_RUNTIME_HEADER_KIND: Final = "stream_runtime_header"
LOCAL_STREAM_RUNTIME_KIND: Final[Literal["local_stream_runtime"]] = "local_stream_runtime"
REDIS_STREAM_RUNTIME_KIND: Final[Literal["redis_stream_runtime"]] = "redis_stream_runtime"
STREAM_POSITIVE_MINIMUM = 1
STREAM_TIMEOUT_MINIMUM = 0.01
STREAM_ORIGIN_MINIMUM_LENGTH = 1
STREAM_QUEUE_CAPACITY_MAXIMUM = 10000
STREAM_DURATION_SECONDS_MAXIMUM = 86400
STREAM_EVENT_BYTES_MAXIMUM = 10485760
STREAM_COLLECTION_EVENTS_MAXIMUM = 100000
STREAM_COLLECTION_BYTES_MAXIMUM = 104857600
STREAM_SESSIONS_MAXIMUM = 100000
STREAM_TTL_SECONDS_MAXIMUM = 86400
STREAM_REPLAY_EVENTS_MAXIMUM = 100000
STREAM_REDIS_CONNECTIONS_MAXIMUM = 10000


class StreamRuntimeMode(StrEnum):
    """流状态后端模式。"""

    LOCAL = LOCAL_STREAM_RUNTIME_KIND
    REDIS = REDIS_STREAM_RUNTIME_KIND


class StreamRuntimeHeader(BaseModel):
    """流运行时公共头。"""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["stream_runtime_header"] = STREAM_RUNTIME_HEADER_KIND
    schema_version: Literal["1.0"] = STREAM_SCHEMA_VERSION
    mode: StreamRuntimeMode
    enabled: bool


class StreamRuntimeDetailBase(BaseModel):
    """流运行时扩展公共字段。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = STREAM_SCHEMA_VERSION
    queue_capacity: int = Field(ge=STREAM_POSITIVE_MINIMUM, le=STREAM_QUEUE_CAPACITY_MAXIMUM)
    send_timeout_seconds: float = Field(ge=STREAM_TIMEOUT_MINIMUM)
    max_duration_seconds: float = Field(
        ge=STREAM_TIMEOUT_MINIMUM, le=STREAM_DURATION_SECONDS_MAXIMUM
    )
    max_event_bytes: int = Field(ge=STREAM_POSITIVE_MINIMUM, le=STREAM_EVENT_BYTES_MAXIMUM)
    collection_max_events: int = Field(
        ge=STREAM_POSITIVE_MINIMUM, le=STREAM_COLLECTION_EVENTS_MAXIMUM
    )
    collection_max_bytes: int = Field(
        ge=STREAM_POSITIVE_MINIMUM, le=STREAM_COLLECTION_BYTES_MAXIMUM
    )
    collection_timeout_seconds: float = Field(ge=STREAM_TIMEOUT_MINIMUM)
    max_sessions: int = Field(ge=STREAM_POSITIVE_MINIMUM, le=STREAM_SESSIONS_MAXIMUM)
    max_sessions_per_subject: int = Field(ge=STREAM_POSITIVE_MINIMUM, le=STREAM_SESSIONS_MAXIMUM)
    max_sessions_per_ip: int = Field(ge=STREAM_POSITIVE_MINIMUM, le=STREAM_SESSIONS_MAXIMUM)
    max_sessions_per_operation: int = Field(ge=STREAM_POSITIVE_MINIMUM, le=STREAM_SESSIONS_MAXIMUM)
    ticket_ttl_seconds: int = Field(ge=STREAM_POSITIVE_MINIMUM, le=STREAM_TTL_SECONDS_MAXIMUM)
    replay_ttl_seconds: int = Field(ge=STREAM_POSITIVE_MINIMUM, le=STREAM_TTL_SECONDS_MAXIMUM)
    replay_max_events: int = Field(ge=STREAM_POSITIVE_MINIMUM, le=STREAM_REPLAY_EVENTS_MAXIMUM)
    sse_heartbeat_seconds: int = Field(ge=STREAM_POSITIVE_MINIMUM)
    sse_retry_milliseconds: int = Field(ge=STREAM_POSITIVE_MINIMUM)
    websocket_max_message_bytes: int = Field(
        ge=STREAM_POSITIVE_MINIMUM, le=STREAM_EVENT_BYTES_MAXIMUM
    )
    websocket_ping_interval_seconds: float = Field(ge=STREAM_TIMEOUT_MINIMUM)
    websocket_ping_timeout_seconds: float = Field(ge=STREAM_TIMEOUT_MINIMUM)
    shutdown_grace_seconds: float = Field(ge=STREAM_TIMEOUT_MINIMUM)
    allowed_origins: list[str] = Field(min_length=STREAM_POSITIVE_MINIMUM)
    require_browser_ticket: bool

    @model_validator(mode="after")
    def validate_limits(self) -> StreamRuntimeDetailBase:
        """校验流运行时组合上限。

        :returns: 已校验运行时扩展。
        :rtype: LocalStreamRuntimeDetail
        :raises ValueError: 配额、字节或时间组合不合理时抛出。
        """

        quotas = (
            self.max_sessions_per_subject,
            self.max_sessions_per_ip,
            self.max_sessions_per_operation,
        )
        if any(quota > self.max_sessions for quota in quotas):
            raise ValueError("流会话维度配额不得大于全局配额。")
        if self.collection_max_bytes < self.max_event_bytes:
            raise ValueError("非流式聚合字节上限不得小于单事件字节上限。")
        if self.collection_timeout_seconds > self.max_duration_seconds:
            raise ValueError("非流式聚合超时不得大于流最大持续时间。")
        normalized_origins = [origin.strip() for origin in self.allowed_origins]
        if any(len(origin) < STREAM_ORIGIN_MINIMUM_LENGTH for origin in normalized_origins):
            raise ValueError("流式 allowed_origins 不得包含空值。")
        return self


class LocalStreamRuntimeDetail(StreamRuntimeDetailBase):
    """本地流运行时扩展。"""

    kind: Literal["local_stream_runtime"] = LOCAL_STREAM_RUNTIME_KIND


class RedisStreamRuntimeDetail(StreamRuntimeDetailBase):
    """Redis 流运行时扩展。"""

    kind: Literal["redis_stream_runtime"] = REDIS_STREAM_RUNTIME_KIND
    redis_key_prefix: str = Field(min_length=STREAM_ORIGIN_MINIMUM_LENGTH)


StreamRuntimeDetail = Annotated[
    LocalStreamRuntimeDetail | RedisStreamRuntimeDetail,
    Field(discriminator="kind"),
]


class StreamRuntimeEnvelope(BaseModel):
    """流运行时信封。"""

    model_config = ConfigDict(extra="forbid")

    envelope_kind: Literal["stream_runtime_envelope"] = STREAM_RUNTIME_ENVELOPE_KIND
    schema_version: Literal["1.0"] = STREAM_SCHEMA_VERSION
    header: StreamRuntimeHeader
    detail: StreamRuntimeDetail

    @model_validator(mode="after")
    def validate_contract(self) -> StreamRuntimeEnvelope:
        """校验运行时公共头与扩展类型、版本一致。

        :returns: 已校验运行时信封。
        :rtype: StreamRuntimeEnvelope
        :raises ValueError: 类型或版本不一致时抛出。
        """

        if self.header.mode != self.detail.kind:
            raise ValueError("流运行时 mode 必须与 detail.kind 一致。")
        if self.schema_version != self.header.schema_version:
            raise ValueError("流运行时信封与公共头 schema_version 必须一致。")
        if self.schema_version != self.detail.schema_version:
            raise ValueError("流运行时信封与扩展 schema_version 必须一致。")
        return self
