"""Codex 控制操作契约。"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.core.codex_contract.thread_contract import CODEX_THREAD_TITLE_MAX_LENGTH

CODEX_OPERATION_PROJECTION_KIND: Final[Literal["codex_operation_projection"]] = (
    "codex_operation_projection"
)
CODEX_OPERATION_PROJECTION_SCHEMA_VERSION: Final[Literal["1.0"]] = "1.0"


class CodexOperationProjectionKind(StrEnum):
    """控制操作允许持久化的强类型派生投影类型。"""

    TURN_SUBMISSION = "turn_submission"


class CodexOperationProjectionHeader(BaseModel):
    """控制操作派生投影公共头。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["codex_operation_projection"] = CODEX_OPERATION_PROJECTION_KIND
    schema_version: Literal["1.0"] = CODEX_OPERATION_PROJECTION_SCHEMA_VERSION
    detail_kind: CodexOperationProjectionKind


class CodexTurnSubmissionProjectionDetail(BaseModel):
    """消息受理后可落库的短标题与活动时间，不包含原始消息。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal[CodexOperationProjectionKind.TURN_SUBMISSION] = (
        CodexOperationProjectionKind.TURN_SUBMISSION
    )
    schema_version: Literal["1.0"] = CODEX_OPERATION_PROJECTION_SCHEMA_VERSION
    display_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=CODEX_THREAD_TITLE_MAX_LENGTH,
    )
    occurred_at: datetime


CodexOperationProjectionDetail = Annotated[
    CodexTurnSubmissionProjectionDetail,
    Field(discriminator="kind"),
]


class CodexOperationProjection(BaseModel):
    """公共头与强类型扩展字段组成的控制操作派生投影。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    header: CodexOperationProjectionHeader
    detail: CodexOperationProjectionDetail

    @model_validator(mode="after")
    def validate_header_and_detail(self) -> CodexOperationProjection:
        """外层类型和版本必须与内层扩展完全一致。"""

        if self.header.detail_kind != self.detail.kind:
            raise ValueError("Codex操作投影公共头类型与扩展字段不一致。")
        if self.header.schema_version != self.detail.schema_version:
            raise ValueError("Codex操作投影公共头版本与扩展字段不一致。")
        return self


class CodexOperationView(BaseModel):
    """浏览器可核对的操作事实，不暴露幂等摘要或内部请求。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    operation_id: UUID
    command_id: UUID
    host_id: UUID
    workspace_id: UUID | None
    thread_id: str | None
    status: str
    error_code: str | None
    updated_at: datetime


class CodexControlOperationSnapshot(BaseModel):
    """可重投且可审计的控制操作元数据。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    operation_id: UUID
    command_id: UUID
    actor_subject_id: str = Field(min_length=1, max_length=128)
    owner_subject_id: str = Field(min_length=1, max_length=128)
    host_id: UUID
    workspace_id: UUID | None = None
    thread_id: str | None = Field(default=None, max_length=256)
    operation_type: str = Field(min_length=1, max_length=64)
    idempotency_key: str = Field(min_length=1, max_length=256)
    request_digest: str = Field(min_length=64, max_length=64)
    status: str = Field(min_length=1, max_length=32)
    dispatch_attempt: int = Field(ge=0)
    last_dispatched_at: datetime | None = None
    ack_deadline_at: datetime | None = None
    error_code: str | None = Field(default=None, max_length=128)
    result_digest: str | None = Field(default=None, max_length=64)
    projection: CodexOperationProjection | None = None
    accepted_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
