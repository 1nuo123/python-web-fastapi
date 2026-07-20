"""
管理员任务管理 HTTP 契约。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.application.admin.read_admin_task_runtime_usecase import (
    AdminTaskRuntimeResult,
)
from src.application.ports.task_runtime_port import TaskRegistrationRuntimeSnapshot
from src.core.task_contract.message_bus_contract import MessageBusBackend
from src.core.task_contract.task_dispatcher_contract import TaskDispatchResultPayload
from src.core.task_contract.task_execution_record_contract import (
    TaskExecutionRecordEnvelope,
    TaskExecutionStage,
    TaskExecutionStatus,
)
from src.core.task_contract.task_registration_contract import (
    FunboostTaskRegistrationDetail,
    LocalTaskRegistrationDetail,
    TaskRegistrationEnvelope,
)
from src.core.task_contract.task_runtime_contract import (
    MessageBackend,
    TaskBackend,
    TaskRuntimeMode,
)

ADMIN_TASK_SCHEMA_VERSION: Final = "1.0"
ADMIN_TASK_EXECUTION_LIST_KIND: Final = "admin_task_execution_list"
ADMIN_TASK_EXECUTION_RECORD_KIND: Final = "admin_task_execution_record"
ADMIN_TASK_EXECUTION_RUNTIME_KIND: Final = "admin_task_execution_runtime"
ADMIN_TASK_RUNTIME_KIND: Final = "admin_task_runtime"
ADMIN_TASK_REGISTRATION_KIND: Final = "admin_task_registration"
ADMIN_TASK_REGISTRATION_LIST_KIND: Final = "admin_task_registration_list"
ADMIN_TASK_DISPATCH_KIND: Final = "admin_task_dispatch"
ADMIN_TASK_DISPATCH_RESULT_KIND: Final = "admin_task_dispatch_result"
ADMIN_TASK_JOB_KIND_MINIMUM_LENGTH = 1
ADMIN_TASK_PAYLOAD_JSON_MINIMUM_LENGTH = 1
ADMIN_TASK_RETRY_LIMIT_MINIMUM = 0
ADMIN_TASK_QUERY_LIMIT_DEFAULT = 50
ADMIN_TASK_QUERY_LIMIT_MINIMUM = 1
ADMIN_TASK_QUERY_LIMIT_MAXIMUM = 200


class AdminTaskOperationName(StrEnum):
    """
    管理员任务操作名称枚举。
    """

    EXECUTION_LIST = "execution_list"
    EXECUTION_RECORD = "execution_record"
    RUNTIME_READ = "runtime_read"
    REGISTRATION_LIST = "registration_list"
    DISPATCH = "dispatch"
    DISPATCH_RESULT = "dispatch_result"


class AdminTaskPayloadKind(StrEnum):
    """
    管理员任务载荷类型枚举。
    """

    EXECUTION_LIST = ADMIN_TASK_EXECUTION_LIST_KIND
    EXECUTION_RECORD = ADMIN_TASK_EXECUTION_RECORD_KIND
    RUNTIME = ADMIN_TASK_RUNTIME_KIND
    REGISTRATION_LIST = ADMIN_TASK_REGISTRATION_LIST_KIND
    DISPATCH = ADMIN_TASK_DISPATCH_KIND
    DISPATCH_RESULT = ADMIN_TASK_DISPATCH_RESULT_KIND


class AdminTaskHeader(BaseModel):
    """
    管理员任务公共头。
    """

    model_config = ConfigDict(extra="forbid")

    kind: AdminTaskPayloadKind
    schema_version: Literal["1.0"] = ADMIN_TASK_SCHEMA_VERSION
    operation_name: AdminTaskOperationName


class AdminTaskExecutionRuntimePayload(BaseModel):
    """
    管理员任务执行运行时载荷。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["admin_task_execution_runtime"] = ADMIN_TASK_EXECUTION_RUNTIME_KIND
    schema_version: Literal["1.0"] = ADMIN_TASK_SCHEMA_VERSION
    status: TaskExecutionStatus
    stage: TaskExecutionStage
    attempt_count: int = Field(ge=ADMIN_TASK_RETRY_LIMIT_MINIMUM)
    started_at_epoch: int | None
    finished_at_epoch: int | None
    failed_at_epoch: int | None
    next_retry_at_epoch: int | None
    last_error_type: str | None
    last_error_message: str | None

    @classmethod
    def from_record(
        cls,
        record: TaskExecutionRecordEnvelope,
    ) -> AdminTaskExecutionRuntimePayload:
        """
        从任务执行记录构建运行时载荷。

        :param record: 任务执行记录信封。
        :type record: TaskExecutionRecordEnvelope
        :returns: 管理员任务执行运行时载荷。
        :rtype: AdminTaskExecutionRuntimePayload
        """

        detail = record.detail
        return cls(
            status=detail.status,
            stage=detail.stage,
            attempt_count=detail.attempt_count,
            started_at_epoch=getattr(detail, "started_at_epoch", None),
            finished_at_epoch=getattr(detail, "finished_at_epoch", None),
            failed_at_epoch=getattr(detail, "failed_at_epoch", None),
            next_retry_at_epoch=getattr(detail, "next_retry_at_epoch", None),
            last_error_type=getattr(detail, "last_error_type", None),
            last_error_message=getattr(detail, "last_error_message", None),
        )


class AdminTaskExecutionRecordPayload(BaseModel):
    """
    管理员任务执行记录载荷。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["admin_task_execution_record"] = ADMIN_TASK_EXECUTION_RECORD_KIND
    schema_version: Literal["1.0"] = ADMIN_TASK_SCHEMA_VERSION
    record_id: str
    task_id: str
    job_kind: str
    deduplication_key: str
    backend: TaskBackend
    queue_name: str
    request_id: str
    trace_id: str | None
    created_at_epoch: int
    runtime: AdminTaskExecutionRuntimePayload

    @classmethod
    def from_record(
        cls,
        record: TaskExecutionRecordEnvelope,
    ) -> AdminTaskExecutionRecordPayload:
        """
        从任务执行记录构建管理员载荷。

        :param record: 任务执行记录信封。
        :type record: TaskExecutionRecordEnvelope
        :returns: 管理员任务执行记录载荷。
        :rtype: AdminTaskExecutionRecordPayload
        """

        return cls(
            record_id=record.header.record_id,
            task_id=record.header.task_id,
            job_kind=record.header.job_kind,
            deduplication_key=record.header.deduplication_key,
            backend=record.header.backend,
            queue_name=record.header.queue_name,
            request_id=record.header.request_id,
            trace_id=record.header.trace_id,
            created_at_epoch=record.header.created_at_epoch,
            runtime=AdminTaskExecutionRuntimePayload.from_record(record),
        )


class AdminTaskExecutionListPayload(BaseModel):
    """
    管理员任务执行记录列表载荷。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["admin_task_execution_list"] = ADMIN_TASK_EXECUTION_LIST_KIND
    schema_version: Literal["1.0"] = ADMIN_TASK_SCHEMA_VERSION
    records: list[AdminTaskExecutionRecordPayload]

    @classmethod
    def from_records(
        cls,
        records: list[TaskExecutionRecordEnvelope],
    ) -> AdminTaskExecutionListPayload:
        """
        从任务执行记录列表构建管理员列表载荷。

        :param records: 任务执行记录信封列表。
        :type records: list[TaskExecutionRecordEnvelope]
        :returns: 管理员任务执行记录列表载荷。
        :rtype: AdminTaskExecutionListPayload
        """

        return cls(
            records=[AdminTaskExecutionRecordPayload.from_record(record) for record in records]
        )


class AdminTaskRuntimePayload(BaseModel):
    """
    管理员任务运行时载荷。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["admin_task_runtime"] = ADMIN_TASK_RUNTIME_KIND
    schema_version: Literal["1.0"] = ADMIN_TASK_SCHEMA_VERSION
    task_runtime_mode: TaskRuntimeMode
    task_backend: TaskBackend
    transport_backend: MessageBusBackend
    configured_transport_backend: MessageBackend
    worker_enabled: bool
    inline_execute_enabled: bool
    default_job_kind: str
    default_retry_limit: int

    @classmethod
    def from_result(
        cls,
        result: AdminTaskRuntimeResult,
    ) -> AdminTaskRuntimePayload:
        """
        从任务运行时结果构建管理员载荷。

        :param result: 管理员任务运行时结果。
        :type result: AdminTaskRuntimeResult
        :returns: 管理员任务运行时载荷。
        :rtype: AdminTaskRuntimePayload
        """

        return cls(
            task_runtime_mode=result.task_runtime_mode,
            task_backend=result.task_backend,
            transport_backend=result.transport_backend,
            configured_transport_backend=result.configured_transport_backend,
            worker_enabled=result.worker_enabled,
            inline_execute_enabled=result.inline_execute_enabled,
            default_job_kind=result.default_job_kind,
            default_retry_limit=result.default_retry_limit,
        )


class AdminTaskRegistrationPayload(BaseModel):
    """
    管理员任务注册项载荷。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["admin_task_registration"] = ADMIN_TASK_REGISTRATION_KIND
    schema_version: Literal["1.0"] = ADMIN_TASK_SCHEMA_VERSION
    task_name: str
    job_kind: str
    enabled: bool
    registration_backend: TaskBackend
    current_runtime_backend: TaskBackend
    active_for_current_runtime: bool
    handler_bound: bool
    payload_model_name: str | None
    retry_limit: int | None
    queue_name: str | None
    exchange_name: str | None
    routing_key: str | None

    @classmethod
    def from_snapshot(
        cls,
        snapshot: TaskRegistrationRuntimeSnapshot,
    ) -> AdminTaskRegistrationPayload:
        """
        从任务注册运行时快照构建管理员载荷。

        :param snapshot: 任务注册运行时快照。
        :type snapshot: TaskRegistrationRuntimeSnapshot
        :returns: 管理员任务注册项载荷。
        :rtype: AdminTaskRegistrationPayload
        """

        registration = snapshot.registration
        detail = registration.detail
        return cls(
            task_name=registration.header.task_name,
            job_kind=registration.header.job_kind,
            enabled=registration.header.enabled,
            registration_backend=snapshot.registration_backend,
            current_runtime_backend=snapshot.current_runtime_backend,
            active_for_current_runtime=snapshot.active_for_current_runtime,
            handler_bound=snapshot.handler_bound,
            payload_model_name=snapshot.payload_model_name,
            retry_limit=cls._read_retry_limit(registration),
            queue_name=(
                detail.queue_name if isinstance(detail, FunboostTaskRegistrationDetail) else None
            ),
            exchange_name=(
                detail.exchange_name if isinstance(detail, FunboostTaskRegistrationDetail) else None
            ),
            routing_key=(
                detail.routing_key if isinstance(detail, FunboostTaskRegistrationDetail) else None
            ),
        )

    @classmethod
    def _read_retry_limit(
        cls,
        registration: TaskRegistrationEnvelope,
    ) -> int | None:
        """
        读取任务注册项重试次数。

        :param registration: 任务注册信封。
        :type registration: TaskRegistrationEnvelope
        :returns: 任务重试次数。
        :rtype: int | None
        """

        detail = registration.detail
        if isinstance(detail, LocalTaskRegistrationDetail):
            return detail.retry_limit
        if isinstance(detail, FunboostTaskRegistrationDetail):
            return detail.retry_limit
        return None


class AdminTaskRegistrationListPayload(BaseModel):
    """
    管理员任务注册列表载荷。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["admin_task_registration_list"] = ADMIN_TASK_REGISTRATION_LIST_KIND
    schema_version: Literal["1.0"] = ADMIN_TASK_SCHEMA_VERSION
    registrations: list[AdminTaskRegistrationPayload]

    @classmethod
    def from_snapshots(
        cls,
        snapshots: list[TaskRegistrationRuntimeSnapshot],
    ) -> AdminTaskRegistrationListPayload:
        """
        从任务注册运行时快照列表构建管理员载荷。

        :param snapshots: 任务注册运行时快照列表。
        :type snapshots: list[TaskRegistrationRuntimeSnapshot]
        :returns: 管理员任务注册列表载荷。
        :rtype: AdminTaskRegistrationListPayload
        """

        return cls(
            registrations=[
                AdminTaskRegistrationPayload.from_snapshot(snapshot) for snapshot in snapshots
            ]
        )


class AdminTaskDispatchDetail(BaseModel):
    """
    管理员任务派发请求扩展字段。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["admin_task_dispatch"] = ADMIN_TASK_DISPATCH_KIND
    schema_version: Literal["1.0"] = ADMIN_TASK_SCHEMA_VERSION
    job_kind: str = Field(min_length=ADMIN_TASK_JOB_KIND_MINIMUM_LENGTH)
    payload_json: str = Field(min_length=ADMIN_TASK_PAYLOAD_JSON_MINIMUM_LENGTH)
    retry_limit: int | None = Field(default=None, ge=ADMIN_TASK_RETRY_LIMIT_MINIMUM)
    deduplication_key: str | None = None


class AdminTaskDispatchResultPayload(BaseModel):
    """
    管理员任务派发结果载荷。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["admin_task_dispatch_result"] = ADMIN_TASK_DISPATCH_RESULT_KIND
    schema_version: Literal["1.0"] = ADMIN_TASK_SCHEMA_VERSION
    task_id: str
    job_kind: str
    dispatched: bool
    retry_limit: int
    backend: TaskBackend
    queue_name: str
    published: bool
    worker_enabled: bool
    inline_execute_enabled: bool | None = None
    execution_status: TaskExecutionStatus
    execution_stage: TaskExecutionStage
    reused_existing_record: bool

    @classmethod
    def from_result(
        cls,
        result: TaskDispatchResultPayload,
    ) -> AdminTaskDispatchResultPayload:
        """
        从任务派发结果构建管理员载荷。

        :param result: 任务派发结果。
        :type result: TaskDispatchResultPayload
        :returns: 管理员任务派发结果载荷。
        :rtype: AdminTaskDispatchResultPayload
        """

        return cls(
            task_id=result.task_id,
            job_kind=result.job_kind,
            dispatched=result.dispatched,
            retry_limit=result.retry_limit,
            backend=result.backend,
            queue_name=result.queue_name,
            published=result.published,
            worker_enabled=result.worker_enabled,
            inline_execute_enabled=result.inline_execute_enabled,
            execution_status=result.execution_status,
            execution_stage=result.execution_stage,
            reused_existing_record=result.reused_existing_record,
        )


AdminTaskExecutionListDetail = Annotated[
    AdminTaskExecutionListPayload,
    Field(discriminator="kind"),
]
AdminTaskExecutionRecordDetail = Annotated[
    AdminTaskExecutionRecordPayload,
    Field(discriminator="kind"),
]
AdminTaskRuntimeDetail = Annotated[
    AdminTaskRuntimePayload,
    Field(discriminator="kind"),
]
AdminTaskRegistrationListDetail = Annotated[
    AdminTaskRegistrationListPayload,
    Field(discriminator="kind"),
]
AdminTaskDispatchDetailUnion = Annotated[
    AdminTaskDispatchDetail,
    Field(discriminator="kind"),
]
AdminTaskDispatchResultDetail = Annotated[
    AdminTaskDispatchResultPayload,
    Field(discriminator="kind"),
]


class AdminTaskExecutionListEnvelope(BaseModel):
    """
    管理员任务执行记录列表信封。
    """

    model_config = ConfigDict(extra="forbid")

    header: AdminTaskHeader
    detail: AdminTaskExecutionListDetail

    @model_validator(mode="after")
    def validate_detail_contract(self) -> AdminTaskExecutionListEnvelope:
        """
        校验任务执行记录列表公共头与扩展字段一致。

        :returns: 当前信封。
        :rtype: AdminTaskExecutionListEnvelope
        """

        if self.header.kind.value != self.detail.kind:
            raise ValueError("任务执行记录列表 header.kind 必须与 detail.kind 一致。")
        if self.header.schema_version != self.detail.schema_version:
            raise ValueError("任务执行记录列表 schema_version 必须一致。")
        return self


class AdminTaskExecutionRecordEnvelope(BaseModel):
    """
    管理员任务执行记录详情信封。
    """

    model_config = ConfigDict(extra="forbid")

    header: AdminTaskHeader
    detail: AdminTaskExecutionRecordDetail

    @model_validator(mode="after")
    def validate_detail_contract(self) -> AdminTaskExecutionRecordEnvelope:
        """
        校验任务执行记录详情公共头与扩展字段一致。

        :returns: 当前信封。
        :rtype: AdminTaskExecutionRecordEnvelope
        """

        if self.header.kind.value != self.detail.kind:
            raise ValueError("任务执行记录详情 header.kind 必须与 detail.kind 一致。")
        if self.header.schema_version != self.detail.schema_version:
            raise ValueError("任务执行记录详情 schema_version 必须一致。")
        return self


class AdminTaskRuntimeEnvelope(BaseModel):
    """
    管理员任务运行时信封。
    """

    model_config = ConfigDict(extra="forbid")

    header: AdminTaskHeader
    detail: AdminTaskRuntimeDetail

    @model_validator(mode="after")
    def validate_detail_contract(self) -> AdminTaskRuntimeEnvelope:
        """
        校验任务运行时公共头与扩展字段一致。

        :returns: 当前信封。
        :rtype: AdminTaskRuntimeEnvelope
        """

        if self.header.kind.value != self.detail.kind:
            raise ValueError("任务运行时 header.kind 必须与 detail.kind 一致。")
        if self.header.schema_version != self.detail.schema_version:
            raise ValueError("任务运行时 schema_version 必须一致。")
        return self


class AdminTaskRegistrationListEnvelope(BaseModel):
    """
    管理员任务注册列表信封。
    """

    model_config = ConfigDict(extra="forbid")

    header: AdminTaskHeader
    detail: AdminTaskRegistrationListDetail

    @model_validator(mode="after")
    def validate_detail_contract(self) -> AdminTaskRegistrationListEnvelope:
        """
        校验任务注册列表公共头与扩展字段一致。

        :returns: 当前信封。
        :rtype: AdminTaskRegistrationListEnvelope
        """

        if self.header.kind.value != self.detail.kind:
            raise ValueError("任务注册列表 header.kind 必须与 detail.kind 一致。")
        if self.header.schema_version != self.detail.schema_version:
            raise ValueError("任务注册列表 schema_version 必须一致。")
        return self


class AdminTaskDispatchEnvelope(BaseModel):
    """
    管理员任务派发请求信封。
    """

    model_config = ConfigDict(extra="forbid")

    header: AdminTaskHeader
    detail: AdminTaskDispatchDetailUnion

    @model_validator(mode="after")
    def validate_detail_contract(self) -> AdminTaskDispatchEnvelope:
        """
        校验任务派发请求公共头与扩展字段一致。

        :returns: 当前信封。
        :rtype: AdminTaskDispatchEnvelope
        """

        if self.header.kind.value != self.detail.kind:
            raise ValueError("任务派发 header.kind 必须与 detail.kind 一致。")
        if self.header.schema_version != self.detail.schema_version:
            raise ValueError("任务派发 schema_version 必须一致。")
        return self


class AdminTaskDispatchResultEnvelope(BaseModel):
    """
    管理员任务派发结果信封。
    """

    model_config = ConfigDict(extra="forbid")

    header: AdminTaskHeader
    detail: AdminTaskDispatchResultDetail

    @model_validator(mode="after")
    def validate_detail_contract(self) -> AdminTaskDispatchResultEnvelope:
        """
        校验任务派发结果公共头与扩展字段一致。

        :returns: 当前信封。
        :rtype: AdminTaskDispatchResultEnvelope
        """

        if self.header.kind.value != self.detail.kind:
            raise ValueError("任务派发结果 header.kind 必须与 detail.kind 一致。")
        if self.header.schema_version != self.detail.schema_version:
            raise ValueError("任务派发结果 schema_version 必须一致。")
        return self
