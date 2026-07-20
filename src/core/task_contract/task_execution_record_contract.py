"""
任务执行记录契约核心模块。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.core.task_contract.task_runtime_contract import TaskBackend

TASK_EXECUTION_RECORD_SCHEMA_VERSION: Final = "1.0"
TASK_EXECUTION_RECORD_KIND: Final = "task_execution_record"
TASK_EXECUTION_PENDING_DETAIL_KIND: Final = "task_execution_pending_detail"
TASK_EXECUTION_RESERVED_DETAIL_KIND: Final = "task_execution_reserved_detail"
TASK_EXECUTION_PUBLISHED_DETAIL_KIND: Final = "task_execution_published_detail"
TASK_EXECUTION_RUNNING_DETAIL_KIND: Final = "task_execution_running_detail"
TASK_EXECUTION_RETRYING_DETAIL_KIND: Final = "task_execution_retrying_detail"
TASK_EXECUTION_SUCCESS_DETAIL_KIND: Final = "task_execution_success_detail"
TASK_EXECUTION_FAILED_DETAIL_KIND: Final = "task_execution_failed_detail"
TASK_EXECUTION_DEDUPE_CREATED_DETAIL_KIND: Final = "task_execution_created"
TASK_EXECUTION_DEDUPE_EXISTING_DETAIL_KIND: Final = "task_execution_existing"
TASK_EXECUTION_STATUS_PENDING = "PENDING"
TASK_EXECUTION_STATUS_RESERVED = "RESERVED"
TASK_EXECUTION_STATUS_PUBLISHED = "PUBLISHED"
TASK_EXECUTION_STATUS_RUNNING = "RUNNING"
TASK_EXECUTION_STATUS_RETRYING = "RETRYING"
TASK_EXECUTION_STATUS_SUCCESS = "SUCCESS"
TASK_EXECUTION_STATUS_FAILED = "FAILED"
TASK_EXECUTION_STAGE_DISPATCH = "dispatch"
TASK_EXECUTION_STAGE_LOCAL = "local_execution"
TASK_EXECUTION_STAGE_CONSUME = "consume_execution"
TASK_EXECUTION_STAGE_STARTUP = "startup_probe"


class TaskExecutionStatus(StrEnum):
    """
    任务执行状态枚举。
    """

    PENDING = TASK_EXECUTION_STATUS_PENDING
    RESERVED = TASK_EXECUTION_STATUS_RESERVED
    PUBLISHED = TASK_EXECUTION_STATUS_PUBLISHED
    RUNNING = TASK_EXECUTION_STATUS_RUNNING
    RETRYING = TASK_EXECUTION_STATUS_RETRYING
    SUCCESS = TASK_EXECUTION_STATUS_SUCCESS
    FAILED = TASK_EXECUTION_STATUS_FAILED


class TaskExecutionStage(StrEnum):
    """
    任务执行阶段枚举。
    """

    DISPATCH = TASK_EXECUTION_STAGE_DISPATCH
    LOCAL_EXECUTION = TASK_EXECUTION_STAGE_LOCAL
    CONSUME_EXECUTION = TASK_EXECUTION_STAGE_CONSUME
    STARTUP_PROBE = TASK_EXECUTION_STAGE_STARTUP


class TaskExecutionRecordDetailKind(StrEnum):
    """
    任务执行记录扩展类型枚举。
    """

    PENDING = TASK_EXECUTION_PENDING_DETAIL_KIND
    RESERVED = TASK_EXECUTION_RESERVED_DETAIL_KIND
    PUBLISHED = TASK_EXECUTION_PUBLISHED_DETAIL_KIND
    RUNNING = TASK_EXECUTION_RUNNING_DETAIL_KIND
    RETRYING = TASK_EXECUTION_RETRYING_DETAIL_KIND
    SUCCESS = TASK_EXECUTION_SUCCESS_DETAIL_KIND
    FAILED = TASK_EXECUTION_FAILED_DETAIL_KIND


class TaskExecutionDedupeDetailKind(StrEnum):
    """
    任务执行去重结果扩展类型枚举。
    """

    CREATED = TASK_EXECUTION_DEDUPE_CREATED_DETAIL_KIND
    EXISTING = TASK_EXECUTION_DEDUPE_EXISTING_DETAIL_KIND


class TaskExecutionRecordHeader(BaseModel):
    """
    任务执行记录公共头。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["task_execution_record"] = TASK_EXECUTION_RECORD_KIND
    schema_version: Literal["1.0"] = TASK_EXECUTION_RECORD_SCHEMA_VERSION
    detail_kind: TaskExecutionRecordDetailKind
    record_id: str
    task_id: str
    job_kind: str
    deduplication_key: str
    backend: TaskBackend
    queue_name: str
    request_id: str
    trace_id: str | None = None
    created_at_epoch: int


class TaskExecutionPendingDetail(BaseModel):
    """
    任务等待态扩展。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["task_execution_pending_detail"] = TASK_EXECUTION_PENDING_DETAIL_KIND
    schema_version: Literal["1.0"] = TASK_EXECUTION_RECORD_SCHEMA_VERSION
    status: Literal[TaskExecutionStatus.PENDING] = TaskExecutionStatus.PENDING
    stage: Literal[TaskExecutionStage.DISPATCH] = TaskExecutionStage.DISPATCH
    attempt_count: int = Field(ge=0)


class TaskExecutionReservedDetail(BaseModel):
    """
    任务预占态扩展。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["task_execution_reserved_detail"] = TASK_EXECUTION_RESERVED_DETAIL_KIND
    schema_version: Literal["1.0"] = TASK_EXECUTION_RECORD_SCHEMA_VERSION
    status: Literal[TaskExecutionStatus.RESERVED] = TaskExecutionStatus.RESERVED
    stage: Literal[TaskExecutionStage.DISPATCH] = TaskExecutionStage.DISPATCH
    attempt_count: int = Field(ge=0)


class TaskExecutionPublishedDetail(BaseModel):
    """
    任务已发布态扩展。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["task_execution_published_detail"] = TASK_EXECUTION_PUBLISHED_DETAIL_KIND
    schema_version: Literal["1.0"] = TASK_EXECUTION_RECORD_SCHEMA_VERSION
    status: Literal[TaskExecutionStatus.PUBLISHED] = TaskExecutionStatus.PUBLISHED
    stage: Literal[TaskExecutionStage.DISPATCH] = TaskExecutionStage.DISPATCH
    attempt_count: int = Field(ge=0)
    published_at_epoch: int


class TaskExecutionRunningDetail(BaseModel):
    """
    任务执行中扩展。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["task_execution_running_detail"] = TASK_EXECUTION_RUNNING_DETAIL_KIND
    schema_version: Literal["1.0"] = TASK_EXECUTION_RECORD_SCHEMA_VERSION
    status: Literal[TaskExecutionStatus.RUNNING] = TaskExecutionStatus.RUNNING
    stage: TaskExecutionStage
    attempt_count: int = Field(ge=0)
    started_at_epoch: int


class TaskExecutionRetryingDetail(BaseModel):
    """
    任务重试中扩展。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["task_execution_retrying_detail"] = TASK_EXECUTION_RETRYING_DETAIL_KIND
    schema_version: Literal["1.0"] = TASK_EXECUTION_RECORD_SCHEMA_VERSION
    status: Literal[TaskExecutionStatus.RETRYING] = TaskExecutionStatus.RETRYING
    stage: TaskExecutionStage
    attempt_count: int = Field(ge=0)
    next_retry_at_epoch: int
    last_error_type: str
    last_error_message: str


class TaskExecutionSuccessDetail(BaseModel):
    """
    任务成功态扩展。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["task_execution_success_detail"] = TASK_EXECUTION_SUCCESS_DETAIL_KIND
    schema_version: Literal["1.0"] = TASK_EXECUTION_RECORD_SCHEMA_VERSION
    status: Literal[TaskExecutionStatus.SUCCESS] = TaskExecutionStatus.SUCCESS
    stage: TaskExecutionStage
    attempt_count: int = Field(ge=0)
    finished_at_epoch: int


class TaskExecutionFailedDetail(BaseModel):
    """
    任务失败态扩展。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["task_execution_failed_detail"] = TASK_EXECUTION_FAILED_DETAIL_KIND
    schema_version: Literal["1.0"] = TASK_EXECUTION_RECORD_SCHEMA_VERSION
    status: Literal[TaskExecutionStatus.FAILED] = TaskExecutionStatus.FAILED
    attempt_count: int = Field(ge=0)
    failed_at_epoch: int
    last_error_type: str
    last_error_message: str
    stage: TaskExecutionStage


TaskExecutionRecordDetailUnion = Annotated[
    TaskExecutionPendingDetail
    | TaskExecutionReservedDetail
    | TaskExecutionPublishedDetail
    | TaskExecutionRunningDetail
    | TaskExecutionRetryingDetail
    | TaskExecutionSuccessDetail
    | TaskExecutionFailedDetail,
    Field(discriminator="kind"),
]


class TaskExecutionRecordEnvelope(BaseModel):
    """
    任务执行记录信封。
    """

    model_config = ConfigDict(extra="forbid")

    header: TaskExecutionRecordHeader
    detail: TaskExecutionRecordDetailUnion

    @model_validator(mode="after")
    def validate_detail_contract(self) -> TaskExecutionRecordEnvelope:
        """
        校验公共头与扩展字段一致性。
        """

        if self.header.detail_kind.value != self.detail.kind:
            raise ValueError("任务执行记录 header.detail_kind 必须与 detail.kind 一致。")
        if self.header.schema_version != self.detail.schema_version:
            raise ValueError("任务执行记录 schema_version 必须一致。")
        return self


class TaskExecutionDedupeHeader(BaseModel):
    """
    任务执行去重结果公共头。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["task_execution_record"] = TASK_EXECUTION_RECORD_KIND
    schema_version: Literal["1.0"] = TASK_EXECUTION_RECORD_SCHEMA_VERSION
    detail_kind: TaskExecutionDedupeDetailKind
    record_id: str
    job_kind: str
    deduplication_key: str


class TaskExecutionCreatedDetail(BaseModel):
    """
    任务执行记录新建结果扩展。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["task_execution_created"] = TASK_EXECUTION_DEDUPE_CREATED_DETAIL_KIND
    schema_version: Literal["1.0"] = TASK_EXECUTION_RECORD_SCHEMA_VERSION
    created: Literal[True] = True
    status: TaskExecutionStatus


class TaskExecutionExistingDetail(BaseModel):
    """
    任务执行记录复用结果扩展。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["task_execution_existing"] = TASK_EXECUTION_DEDUPE_EXISTING_DETAIL_KIND
    schema_version: Literal["1.0"] = TASK_EXECUTION_RECORD_SCHEMA_VERSION
    created: Literal[False] = False
    status: TaskExecutionStatus


TaskExecutionDedupeDetailUnion = Annotated[
    TaskExecutionCreatedDetail | TaskExecutionExistingDetail,
    Field(discriminator="kind"),
]


class TaskExecutionDedupeResult(BaseModel):
    """
    任务执行去重结果信封。
    """

    model_config = ConfigDict(extra="forbid")

    header: TaskExecutionDedupeHeader
    detail: TaskExecutionDedupeDetailUnion

    @model_validator(mode="after")
    def validate_detail_contract(self) -> TaskExecutionDedupeResult:
        """
        校验公共头与扩展字段一致性。
        """

        if self.header.detail_kind.value != self.detail.kind:
            raise ValueError("任务执行去重 header.detail_kind 必须与 detail.kind 一致。")
        if self.header.schema_version != self.detail.schema_version:
            raise ValueError("任务执行去重 schema_version 必须一致。")
        return self
