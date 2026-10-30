"""有界历史表示、正文范围与连接预算的跨进程契约。"""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_SAFE_CONTENT_OFFSET = 2**53 - 1
MAX_CONTENT_REFERENCE_CHARS = 8192
CONTENT_PREVIEW_CHARS = 2048
MIN_CONTENT_MESSAGE_BYTES = 16 * 1024
MAX_CONTROL_MESSAGE_BYTES = 4 * 1024 * 1024


class ContentField(StrEnum):
    TEXT = "text"
    OUTPUT = "output"
    DIFF = "diff"


class ContentErrorCode(StrEnum):
    REVISION_STALE = "content_revision_stale"
    REFERENCE_EXPIRED = "content_reference_expired"
    RANGE_INVALID = "content_range_invalid"
    CAPABILITY_UNAVAILABLE = "content_capability_unavailable"
    SOURCE_ITEM_TOO_LARGE = "source_item_too_large"
    OVERLOADED = "content_read_overloaded"
    TIMEOUT = "content_read_timeout"
    MESSAGE_TOO_LARGE = "message_too_large"


class ContentReadError(ValueError):
    def __init__(self, code: ContentErrorCode) -> None:
        self.code = code
        super().__init__(code.value)


class ContentDescriptorBase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    field: ContentField
    revision: str = Field(min_length=1, max_length=128)
    total_bytes: int | None = Field(default=None, ge=0, le=MAX_SAFE_CONTENT_OFFSET)


class InlineContentDescriptor(ContentDescriptorBase):
    availability: Literal["inline"] = "inline"
    text: str = Field(max_length=CONTENT_PREVIEW_CHARS)


class ReadableContentDescriptor(ContentDescriptorBase):
    availability: Literal["readable"] = "readable"
    preview: str = Field(max_length=CONTENT_PREVIEW_CHARS)
    content_ref: str = Field(min_length=1, max_length=MAX_CONTENT_REFERENCE_CHARS, repr=False)
    expires_at: datetime


class UnavailableContentDescriptor(ContentDescriptorBase):
    availability: Literal["unavailable"] = "unavailable"
    preview: str = Field(max_length=CONTENT_PREVIEW_CHARS)
    unavailable_reason: ContentErrorCode


ContentDescriptor = Annotated[
    InlineContentDescriptor | ReadableContentDescriptor | UnavailableContentDescriptor,
    Field(discriminator="availability"),
]


class CodexContentReadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    content_ref: str = Field(min_length=1, max_length=MAX_CONTENT_REFERENCE_CHARS, repr=False)
    revision: str = Field(min_length=1, max_length=128)
    offset: int = Field(default=0, ge=0, le=MAX_SAFE_CONTENT_OFFSET)
    requested_bytes: int = Field(default=16384, ge=4, le=64 * 1024)


class AgentContentReadRequest(CodexContentReadRequest):
    workspace_key: str = Field(min_length=1, max_length=128)
    thread_id: str = Field(min_length=1, max_length=256)
    item_id: str = Field(min_length=1, max_length=256)
    field: ContentField


class CodexContentChunk(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["codex_content_chunk"] = "codex_content_chunk"
    schema_version: Literal["1.0"] = "1.0"
    revision: str = Field(min_length=1, max_length=128)
    offset: int = Field(ge=0, le=MAX_SAFE_CONTENT_OFFSET)
    next_offset: int = Field(ge=0, le=MAX_SAFE_CONTENT_OFFSET)
    text: str = Field(max_length=64 * 1024)
    eof: bool
    total_bytes: int | None = Field(default=None, ge=0, le=MAX_SAFE_CONTENT_OFFSET)


class AgentContentBudgets(BaseModel):
    """接收能力和本端发送政策取交集；数值由容量实验选择。"""

    model_config = ConfigDict(extra="forbid", frozen=True)
    max_receive_message_bytes: int = Field(
        default=MAX_CONTROL_MESSAGE_BYTES, ge=MIN_CONTENT_MESSAGE_BYTES, le=64 * 1024 * 1024
    )
    history_page_max_bytes: int = Field(
        default=128 * 1024, ge=MIN_CONTENT_MESSAGE_BYTES, le=256 * 1024
    )
    content_chunk_max_message_bytes: int = Field(
        default=16 * 1024, ge=MIN_CONTENT_MESSAGE_BYTES, le=64 * 1024
    )
    query_inflight_max_bytes: int = Field(default=256 * 1024, ge=128 * 1024, le=512 * 1024)
    content_read: bool = True

    @model_validator(mode="after")
    def validate_capacity(self):
        if self.query_inflight_max_bytes < max(
            self.history_page_max_bytes, self.content_chunk_max_message_bytes
        ):
            raise ValueError("查询在途预算必须能够容纳单页或单块。")
        if self.max_receive_message_bytes < max(
            self.history_page_max_bytes, self.content_chunk_max_message_bytes
        ):
            raise ValueError("页与块预算不得超过接收消息上限。")
        return self

    def intersect(self, other: "AgentContentBudgets") -> "AgentContentBudgets":
        receive = min(self.max_receive_message_bytes, other.max_receive_message_bytes)
        return AgentContentBudgets(
            max_receive_message_bytes=receive,
            history_page_max_bytes=min(
                receive, self.history_page_max_bytes, other.history_page_max_bytes
            ),
            content_chunk_max_message_bytes=min(
                receive, self.content_chunk_max_message_bytes, other.content_chunk_max_message_bytes
            ),
            query_inflight_max_bytes=min(
                self.query_inflight_max_bytes, other.query_inflight_max_bytes
            ),
            content_read=self.content_read and other.content_read,
        )
