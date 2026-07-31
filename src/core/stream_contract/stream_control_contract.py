"""WebSocket 客户端控制帧契约。"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Final, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.core.stream_contract.stream_event_contract import STREAM_SCHEMA_VERSION

STREAM_CLIENT_CONTROL_HEADER_KIND: Final = "stream_client_control_header"
STREAM_CLIENT_CONTROL_ENVELOPE_KIND: Final = "stream_client_control_envelope"
STREAM_SUBSCRIBE_CONTROL_KIND: Final = "subscribe"
STREAM_RESUME_CONTROL_KIND: Final = "resume"
STREAM_CANCEL_CONTROL_KIND: Final = "cancel"
STREAM_PING_CONTROL_KIND: Final = "ping"
STREAM_CONTROL_TEXT_MINIMUM_LENGTH = 1


class StreamControlKind(StrEnum):
    """客户端控制帧类型。"""

    SUBSCRIBE = STREAM_SUBSCRIBE_CONTROL_KIND
    RESUME = STREAM_RESUME_CONTROL_KIND
    CANCEL = STREAM_CANCEL_CONTROL_KIND
    PING = STREAM_PING_CONTROL_KIND


class StreamClientControlHeader(BaseModel):
    """客户端控制帧公共头。"""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["stream_client_control_header"] = STREAM_CLIENT_CONTROL_HEADER_KIND
    schema_version: Literal["1.0"] = STREAM_SCHEMA_VERSION
    control_kind: StreamControlKind


T_StreamCommand = TypeVar("T_StreamCommand", bound=BaseModel)


class SubscribeControlDetail(BaseModel, Generic[T_StreamCommand]):
    """首次订阅控制扩展。"""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["subscribe"] = STREAM_SUBSCRIBE_CONTROL_KIND
    schema_version: Literal["1.0"] = STREAM_SCHEMA_VERSION
    command: T_StreamCommand


class ResumeControlDetail(BaseModel):
    """恢复控制扩展。"""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["resume"] = STREAM_RESUME_CONTROL_KIND
    schema_version: Literal["1.0"] = STREAM_SCHEMA_VERSION
    stream_id: str = Field(min_length=STREAM_CONTROL_TEXT_MINIMUM_LENGTH)
    last_event_id: str = Field(min_length=STREAM_CONTROL_TEXT_MINIMUM_LENGTH)


class CancelControlDetail(BaseModel):
    """取消控制扩展。"""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["cancel"] = STREAM_CANCEL_CONTROL_KIND
    schema_version: Literal["1.0"] = STREAM_SCHEMA_VERSION
    reason: str | None = None


class PingControlDetail(BaseModel):
    """客户端探活控制扩展。"""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["ping"] = STREAM_PING_CONTROL_KIND
    schema_version: Literal["1.0"] = STREAM_SCHEMA_VERSION
    nonce: str = Field(min_length=STREAM_CONTROL_TEXT_MINIMUM_LENGTH)


StreamNonSubscribeControlDetail = Annotated[
    ResumeControlDetail | CancelControlDetail | PingControlDetail,
    Field(discriminator="kind"),
]

T_StreamControlDetail = TypeVar("T_StreamControlDetail", bound=BaseModel)


class StreamClientControlEnvelope(BaseModel, Generic[T_StreamControlDetail]):
    """客户端控制帧泛型信封。"""

    model_config = ConfigDict(extra="forbid")

    envelope_kind: Literal["stream_client_control_envelope"] = STREAM_CLIENT_CONTROL_ENVELOPE_KIND
    schema_version: Literal["1.0"] = STREAM_SCHEMA_VERSION
    header: StreamClientControlHeader
    detail: T_StreamControlDetail

    @model_validator(mode="after")
    def validate_contract(self) -> StreamClientControlEnvelope[T_StreamControlDetail]:
        """校验控制头与扩展类型、版本一致。

        :returns: 已校验控制信封。
        :rtype: StreamClientControlEnvelope[T_StreamControlDetail]
        :raises ValueError: 类型或版本不一致时抛出。
        """

        if self.header.control_kind != getattr(self.detail, "kind", None):
            raise ValueError("控制帧公共头类型必须与扩展字段类型一致。")
        if self.schema_version != self.header.schema_version:
            raise ValueError("控制帧信封与公共头 schema_version 必须一致。")
        if self.schema_version != getattr(self.detail, "schema_version", None):
            raise ValueError("控制帧 schema_version 必须一致。")
        return self
