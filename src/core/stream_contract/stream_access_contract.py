"""流访问票据与恢复契约。"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.core.stream_contract.stream_event_contract import STREAM_SCHEMA_VERSION

STREAM_ACCESS_TICKET_KIND: Final = "stream_access_ticket"
STREAM_ACCESS_TICKET_HEADER_KIND: Final = "stream_access_ticket_header"
STREAM_ACCESS_TICKET_ISSUED_KIND: Final = "stream_access_ticket_issued"
STREAM_ACCESS_TICKET_REJECTED_KIND: Final = "stream_access_ticket_rejected"
STREAM_TICKET_TEXT_MINIMUM_LENGTH = 1


class StreamAccessTicketResultKind(StrEnum):
    """访问票据签发结果类型。"""

    ISSUED = STREAM_ACCESS_TICKET_ISSUED_KIND
    REJECTED = STREAM_ACCESS_TICKET_REJECTED_KIND


class StreamAccessTicketHeader(BaseModel):
    """访问票据公共头。"""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["stream_access_ticket_header"] = STREAM_ACCESS_TICKET_HEADER_KIND
    schema_version: Literal["1.0"] = STREAM_SCHEMA_VERSION
    subject_id: str = Field(min_length=STREAM_TICKET_TEXT_MINIMUM_LENGTH)
    operation_name: str = Field(min_length=STREAM_TICKET_TEXT_MINIMUM_LENGTH)
    result_kind: StreamAccessTicketResultKind


class StreamAccessTicketIssuedDetail(BaseModel):
    """仅在签发响应中出现一次的票据明文扩展。"""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["stream_access_ticket_issued"] = STREAM_ACCESS_TICKET_ISSUED_KIND
    schema_version: Literal["1.0"] = STREAM_SCHEMA_VERSION
    ticket: str = Field(min_length=STREAM_TICKET_TEXT_MINIMUM_LENGTH)
    client_ip: str | None
    expires_at: datetime


class StreamAccessTicketRejectedDetail(BaseModel):
    """访问票据签发拒绝扩展。"""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["stream_access_ticket_rejected"] = STREAM_ACCESS_TICKET_REJECTED_KIND
    schema_version: Literal["1.0"] = STREAM_SCHEMA_VERSION
    error_code: str = Field(min_length=STREAM_TICKET_TEXT_MINIMUM_LENGTH)
    message: str = Field(min_length=STREAM_TICKET_TEXT_MINIMUM_LENGTH)


StreamAccessTicketDetail = Annotated[
    StreamAccessTicketIssuedDetail | StreamAccessTicketRejectedDetail,
    Field(discriminator="kind"),
]


class StreamAccessTicketEnvelope(BaseModel):
    """访问票据签发公开信封。"""

    model_config = ConfigDict(extra="forbid")

    envelope_kind: Literal["stream_access_ticket"] = STREAM_ACCESS_TICKET_KIND
    schema_version: Literal["1.0"] = STREAM_SCHEMA_VERSION
    header: StreamAccessTicketHeader
    detail: StreamAccessTicketDetail

    @model_validator(mode="after")
    def validate_contract(self) -> StreamAccessTicketEnvelope:
        """校验访问票据信封类型和三层版本一致。"""

        if self.header.result_kind != self.detail.kind:
            raise ValueError("访问票据公共头类型必须与扩展字段类型一致。")
        if self.schema_version != self.header.schema_version:
            raise ValueError("访问票据信封与公共头 schema_version 必须一致。")
        if self.schema_version != self.detail.schema_version:
            raise ValueError("访问票据信封与扩展 schema_version 必须一致。")
        return self


class StreamAccessTicketRecord(BaseModel):
    """状态存储中的票据摘要记录。"""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["stream_access_ticket_record"] = "stream_access_ticket_record"
    schema_version: Literal["1.0"] = STREAM_SCHEMA_VERSION
    ticket_digest: str = Field(min_length=STREAM_TICKET_TEXT_MINIMUM_LENGTH)
    subject_id: str = Field(min_length=STREAM_TICKET_TEXT_MINIMUM_LENGTH)
    operation_name: str = Field(min_length=STREAM_TICKET_TEXT_MINIMUM_LENGTH)
    client_ip: str | None
    expires_at: datetime


class StreamTicketConsumptionRequest(BaseModel):
    """票据消费请求。"""

    model_config = ConfigDict(extra="forbid")

    ticket_digest: str = Field(min_length=STREAM_TICKET_TEXT_MINIMUM_LENGTH)
    subject_id: str = Field(min_length=STREAM_TICKET_TEXT_MINIMUM_LENGTH)
    operation_name: str = Field(min_length=STREAM_TICKET_TEXT_MINIMUM_LENGTH)
    client_ip: str | None
    consumed_at: datetime


class StreamResumeRequest(BaseModel):
    """有限窗口恢复请求。"""

    model_config = ConfigDict(extra="forbid")

    stream_id: str = Field(min_length=STREAM_TICKET_TEXT_MINIMUM_LENGTH)
    last_event_id: str = Field(min_length=STREAM_TICKET_TEXT_MINIMUM_LENGTH)
    subject_id: str = Field(min_length=STREAM_TICKET_TEXT_MINIMUM_LENGTH)
    operation_name: str = Field(min_length=STREAM_TICKET_TEXT_MINIMUM_LENGTH)


class StreamReplayEventRecord(BaseModel):
    """状态存储中的有限重放事件记录。"""

    model_config = ConfigDict(extra="forbid")

    stream_id: str = Field(min_length=STREAM_TICKET_TEXT_MINIMUM_LENGTH)
    event_id: str = Field(min_length=STREAM_TICKET_TEXT_MINIMUM_LENGTH)
    sequence: int = Field(ge=0)
    subject_id: str = Field(min_length=STREAM_TICKET_TEXT_MINIMUM_LENGTH)
    operation_name: str = Field(min_length=STREAM_TICKET_TEXT_MINIMUM_LENGTH)
    payload_json: str = Field(min_length=STREAM_TICKET_TEXT_MINIMUM_LENGTH)
    expires_at: datetime


class StreamReplayWindow(BaseModel):
    """有限重放窗口查询结果。"""

    model_config = ConfigDict(extra="forbid")

    stream_id: str = Field(min_length=STREAM_TICKET_TEXT_MINIMUM_LENGTH)
    events: list[StreamReplayEventRecord]
    earliest_event_id: str | None
    latest_event_id: str | None
    expired: bool

    @model_validator(mode="after")
    def validate_window(self) -> StreamReplayWindow:
        """校验窗口摘要与事件集合一致。

        :returns: 已校验窗口。
        :rtype: StreamReplayWindow
        :raises ValueError: 摘要与事件集合不一致时抛出。
        """

        if not self.events:
            if self.earliest_event_id is not None or self.latest_event_id is not None:
                raise ValueError("空恢复窗口不得声明最早或最新事件标识。")
            return self
        if self.earliest_event_id != self.events[0].event_id:
            raise ValueError("恢复窗口最早事件标识不一致。")
        if self.latest_event_id != self.events[-1].event_id:
            raise ValueError("恢复窗口最新事件标识不一致。")
        return self
