"""通用 versioned opaque cursor 流契约。"""

from __future__ import annotations

import base64
from datetime import datetime
from typing import Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

CURSOR_STREAM_SCHEMA_VERSION: Final = "2.0"
OPAQUE_CURSOR_PREFIX: Final = "c2."


class OpaqueStreamCursorCodec:
    """将后端 cursor 编码为不泄漏结构的 URL-safe 字符串。"""

    @classmethod
    def encode(cls, value: str) -> str:
        encoded = base64.urlsafe_b64encode(value.encode("ascii")).decode("ascii").rstrip("=")
        return f"{OPAQUE_CURSOR_PREFIX}{encoded}"

    @classmethod
    def decode(cls, value: str) -> str:
        if not value.startswith(OPAQUE_CURSOR_PREFIX):
            raise ValueError("流cursor版本无效。")
        encoded = value[len(OPAQUE_CURSOR_PREFIX) :]
        padding = "=" * (-len(encoded) % 4)
        try:
            return base64.urlsafe_b64decode(f"{encoded}{padding}").decode("ascii")
        except (UnicodeDecodeError, ValueError) as exc:
            raise ValueError("流cursor编码无效。") from exc


class CursorStreamEvent(BaseModel):
    """通用流中的不可变事件记录。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["2.0"] = CURSOR_STREAM_SCHEMA_VERSION
    stream_key: str = Field(min_length=1, max_length=256)
    owner_subject_id: str = Field(min_length=1, max_length=128)
    event_id: UUID
    payload: bytes = Field(max_length=10_485_760)
    expires_at: datetime


class CursorStreamAppendRequest(BaseModel):
    """追加事件及容量、TTL 约束。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event: CursorStreamEvent
    max_events: int = Field(gt=0, le=100_000)


class CursorStreamAppendResult(BaseModel):
    """事件追加结果。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    stream_key: str
    event_id: UUID
    cursor: str = Field(min_length=4, max_length=512)


class CursorStreamReadRequest(BaseModel):
    """按 owner 和 opaque cursor 读取窗口。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    stream_key: str = Field(min_length=1, max_length=256)
    owner_subject_id: str = Field(min_length=1, max_length=128)
    after_cursor: str | None = Field(default=None, max_length=512)
    through_cursor: str | None = Field(default=None, max_length=512)
    limit: int = Field(default=100, gt=0, le=1_000)


class CursorStreamWindow(BaseModel):
    """有限读取窗口；trim 后必须显式 gap。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    stream_key: str
    events: tuple[CursorStreamEvent, ...]
    cursors: tuple[str, ...]
    next_cursor: str | None = None
    tail_cursor: str | None = None
    gap: bool = False
    snapshot_required: bool = False
