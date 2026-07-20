"""
管理员日志与安全事件查询 HTTP 契约。
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.application.ports.admin_log_query_port import (
    AdminLogRecordSnapshot,
    AdminUnparsedLogDetail,
)
from src.core.http_contract.runtime_resource_contract import RuntimeResourceStatus
from src.core.logging_contract.log_event_contract import (
    ACCESS_LOG_DETAIL_KIND,
    EXCEPTION_LOG_DETAIL_KIND,
    RESOURCE_LIFECYCLE_LOG_DETAIL_KIND,
    SECURITY_LOG_DETAIL_KIND,
    TASK_FAILURE_LOG_DETAIL_KIND,
    AccessLogDetail,
    ExceptionLogDetail,
    LogEventKind,
    LogLevel,
    ResourceLifecycleAction,
    ResourceLifecycleLogDetail,
    SecurityLogDetail,
    TaskFailureLogDetail,
)
from src.core.security_contract.security_event_contract import SecurityEventEnvelope

ADMIN_LOG_SCHEMA_VERSION: Final = "1.0"
ADMIN_LOG_RECORD_LIST_KIND: Final = "admin_log_record_list"
ADMIN_SECURITY_EVENT_LIST_KIND: Final = "admin_security_event_list"
ADMIN_ACCESS_LOG_DETAIL_KIND: Final = "admin_access_log_detail"
ADMIN_EXCEPTION_LOG_DETAIL_KIND: Final = "admin_exception_log_detail"
ADMIN_RESOURCE_LIFECYCLE_LOG_DETAIL_KIND: Final = "admin_resource_lifecycle_log_detail"
ADMIN_TASK_FAILURE_LOG_DETAIL_KIND: Final = "admin_task_failure_log_detail"
ADMIN_SECURITY_LOG_DETAIL_KIND: Final = "admin_security_log_detail"
ADMIN_UNPARSED_LOG_DETAIL_KIND: Final = "admin_unparsed_log_detail"
ADMIN_LOG_QUERY_LIMIT_DEFAULT = 50
ADMIN_LOG_QUERY_LIMIT_MINIMUM = 1
ADMIN_LOG_QUERY_LIMIT_MAXIMUM = 200
ADMIN_LOG_UNSUPPORTED_DETAIL_SUMMARY = "日志详情类型暂不支持管理员接口展示。"


class AdminLogOperationName(StrEnum):
    """
    管理员日志查询操作名称枚举。
    """

    LOG_RECORD_LIST = "log_record_list"
    SECURITY_EVENT_LIST = "security_event_list"


class AdminLogPayloadKind(StrEnum):
    """
    管理员日志载荷类型枚举。
    """

    LOG_RECORD_LIST = ADMIN_LOG_RECORD_LIST_KIND
    SECURITY_EVENT_LIST = ADMIN_SECURITY_EVENT_LIST_KIND


class AdminLogHeader(BaseModel):
    """
    管理员日志查询公共头。
    """

    model_config = ConfigDict(extra="forbid")

    kind: AdminLogPayloadKind
    schema_version: Literal["1.0"] = ADMIN_LOG_SCHEMA_VERSION
    operation_name: AdminLogOperationName


class AdminAccessLogDetailPayload(BaseModel):
    """
    管理员访问日志脱敏扩展字段。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["admin_access_log_detail"] = ADMIN_ACCESS_LOG_DETAIL_KIND
    schema_version: Literal["1.0"] = ADMIN_LOG_SCHEMA_VERSION
    source_kind: Literal["access"] = ACCESS_LOG_DETAIL_KIND
    request_path: str
    request_method: str
    status_code: int
    elapsed_milliseconds: float
    route_name: str | None

    @classmethod
    def from_detail(cls, detail: AccessLogDetail) -> AdminAccessLogDetailPayload:
        """
        从访问日志扩展字段构建管理员脱敏载荷。

        :param detail: 访问日志扩展字段。
        :type detail: AccessLogDetail
        :returns: 管理员访问日志脱敏载荷。
        :rtype: AdminAccessLogDetailPayload
        """

        return cls(
            request_path=detail.request_path,
            request_method=detail.request_method,
            status_code=detail.status_code,
            elapsed_milliseconds=detail.elapsed_milliseconds,
            route_name=detail.route_name,
        )


class AdminExceptionLogDetailPayload(BaseModel):
    """
    管理员异常日志脱敏扩展字段。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["admin_exception_log_detail"] = ADMIN_EXCEPTION_LOG_DETAIL_KIND
    schema_version: Literal["1.0"] = ADMIN_LOG_SCHEMA_VERSION
    source_kind: Literal["exception"] = EXCEPTION_LOG_DETAIL_KIND
    request_path: str
    request_method: str
    status_code: int
    error_code: str
    exception_type: str

    @classmethod
    def from_detail(
        cls,
        detail: ExceptionLogDetail,
    ) -> AdminExceptionLogDetailPayload:
        """
        从异常日志扩展字段构建管理员脱敏载荷。

        :param detail: 异常日志扩展字段。
        :type detail: ExceptionLogDetail
        :returns: 管理员异常日志脱敏载荷。
        :rtype: AdminExceptionLogDetailPayload
        """

        return cls(
            request_path=detail.request_path,
            request_method=detail.request_method,
            status_code=detail.status_code,
            error_code=detail.error_code,
            exception_type=detail.exception_type,
        )


class AdminResourceLifecycleLogDetailPayload(BaseModel):
    """
    管理员资源生命周期日志扩展字段。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["admin_resource_lifecycle_log_detail"] = ADMIN_RESOURCE_LIFECYCLE_LOG_DETAIL_KIND
    schema_version: Literal["1.0"] = ADMIN_LOG_SCHEMA_VERSION
    source_kind: Literal["resource_lifecycle"] = RESOURCE_LIFECYCLE_LOG_DETAIL_KIND
    resource_name: str
    lifecycle_action: ResourceLifecycleAction
    resource_status: RuntimeResourceStatus
    detail: str | None

    @classmethod
    def from_detail(
        cls,
        detail: ResourceLifecycleLogDetail,
    ) -> AdminResourceLifecycleLogDetailPayload:
        """
        从资源生命周期日志扩展字段构建管理员载荷。

        :param detail: 资源生命周期日志扩展字段。
        :type detail: ResourceLifecycleLogDetail
        :returns: 管理员资源生命周期日志载荷。
        :rtype: AdminResourceLifecycleLogDetailPayload
        """

        return cls(
            resource_name=detail.resource_name,
            lifecycle_action=detail.lifecycle_action,
            resource_status=detail.resource_status,
            detail=detail.detail,
        )


class AdminTaskFailureLogDetailPayload(BaseModel):
    """
    管理员任务失败日志脱敏扩展字段。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["admin_task_failure_log_detail"] = ADMIN_TASK_FAILURE_LOG_DETAIL_KIND
    schema_version: Literal["1.0"] = ADMIN_LOG_SCHEMA_VERSION
    source_kind: Literal["task_failure"] = TASK_FAILURE_LOG_DETAIL_KIND
    task_id: str
    job_kind: str
    backend: str
    stage: str
    retry_count: int
    queue_name: str | None
    payload_kind: str | None
    request_id: str | None
    trace_id: str | None
    deduplication_key: str | None
    attempt_count: int

    @classmethod
    def from_detail(
        cls,
        detail: TaskFailureLogDetail,
    ) -> AdminTaskFailureLogDetailPayload:
        """
        从任务失败日志扩展字段构建管理员脱敏载荷。

        :param detail: 任务失败日志扩展字段。
        :type detail: TaskFailureLogDetail
        :returns: 管理员任务失败日志脱敏载荷。
        :rtype: AdminTaskFailureLogDetailPayload
        """

        return cls(
            task_id=detail.task_id,
            job_kind=detail.job_kind,
            backend=detail.backend,
            stage=detail.stage,
            retry_count=detail.retry_count,
            queue_name=detail.queue_name,
            payload_kind=detail.payload_kind,
            request_id=detail.request_id,
            trace_id=detail.trace_id,
            deduplication_key=detail.deduplication_key,
            attempt_count=detail.attempt_count,
        )


class AdminSecurityLogDetailPayload(BaseModel):
    """
    管理员安全日志扩展字段。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["admin_security_log_detail"] = ADMIN_SECURITY_LOG_DETAIL_KIND
    schema_version: Literal["1.0"] = ADMIN_LOG_SCHEMA_VERSION
    source_kind: Literal["security"] = SECURITY_LOG_DETAIL_KIND
    security_event: SecurityEventEnvelope

    @classmethod
    def from_detail(
        cls,
        detail: SecurityLogDetail,
    ) -> AdminSecurityLogDetailPayload:
        """
        从安全日志扩展字段构建管理员载荷。

        :param detail: 安全日志扩展字段。
        :type detail: SecurityLogDetail
        :returns: 管理员安全日志载荷。
        :rtype: AdminSecurityLogDetailPayload
        """

        return cls(security_event=detail.security_event)


class AdminUnparsedLogDetailPayload(BaseModel):
    """
    管理员不可解析日志详情摘要。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["admin_unparsed_log_detail"] = ADMIN_UNPARSED_LOG_DETAIL_KIND
    schema_version: Literal["1.0"] = ADMIN_LOG_SCHEMA_VERSION
    summary: str

    @classmethod
    def from_detail(
        cls,
        detail: AdminUnparsedLogDetail,
    ) -> AdminUnparsedLogDetailPayload:
        """
        从不可解析日志详情构建管理员摘要载荷。

        :param detail: 不可解析日志详情。
        :type detail: AdminUnparsedLogDetail
        :returns: 管理员不可解析日志详情摘要。
        :rtype: AdminUnparsedLogDetailPayload
        """

        return cls(summary=detail.summary)


AdminLogRecordDetailPayload = Annotated[
    AdminAccessLogDetailPayload
    | AdminExceptionLogDetailPayload
    | AdminResourceLifecycleLogDetailPayload
    | AdminTaskFailureLogDetailPayload
    | AdminSecurityLogDetailPayload
    | AdminUnparsedLogDetailPayload,
    Field(discriminator="kind"),
]


class AdminLogRecordDetailMapper:
    """
    管理员日志详情脱敏映射器。
    """

    @classmethod
    def from_snapshot_detail(
        cls,
        detail: (
            AccessLogDetail
            | ExceptionLogDetail
            | ResourceLifecycleLogDetail
            | TaskFailureLogDetail
            | SecurityLogDetail
            | AdminUnparsedLogDetail
        ),
    ) -> AdminLogRecordDetailPayload:
        """
        从日志详情快照构建管理员脱敏详情。

        :param detail: 日志详情快照。
        :type detail: LogDetailUnion | AdminUnparsedLogDetail
        :returns: 管理员脱敏日志详情。
        :rtype: AdminLogRecordDetailPayload
        """

        if isinstance(detail, AccessLogDetail):
            return AdminAccessLogDetailPayload.from_detail(detail)
        if isinstance(detail, ExceptionLogDetail):
            return AdminExceptionLogDetailPayload.from_detail(detail)
        if isinstance(detail, ResourceLifecycleLogDetail):
            return AdminResourceLifecycleLogDetailPayload.from_detail(detail)
        if isinstance(detail, TaskFailureLogDetail):
            return AdminTaskFailureLogDetailPayload.from_detail(detail)
        if isinstance(detail, SecurityLogDetail):
            return AdminSecurityLogDetailPayload.from_detail(detail)
        if isinstance(detail, AdminUnparsedLogDetail):
            return AdminUnparsedLogDetailPayload.from_detail(detail)
        return AdminUnparsedLogDetailPayload(summary=ADMIN_LOG_UNSUPPORTED_DETAIL_SUMMARY)


class AdminLogRecordPayload(BaseModel):
    """
    管理员日志记录载荷。
    """

    model_config = ConfigDict(extra="forbid")

    event_id: str
    event_kind: LogEventKind
    schema_version: str
    level: LogLevel
    message: str
    occurred_at: datetime
    request_id: str | None
    trace_id: str | None
    authenticated_subject_id: str | None
    source_module: str
    source_component: str
    detail: AdminLogRecordDetailPayload

    @classmethod
    def from_snapshot(
        cls,
        snapshot: AdminLogRecordSnapshot,
    ) -> AdminLogRecordPayload:
        """
        从管理员日志记录快照构建 HTTP 载荷。

        :param snapshot: 管理员日志记录快照。
        :type snapshot: AdminLogRecordSnapshot
        :returns: 管理员日志记录载荷。
        :rtype: AdminLogRecordPayload
        """

        return cls(
            event_id=snapshot.event_id,
            event_kind=snapshot.event_kind,
            schema_version=snapshot.schema_version,
            level=snapshot.level,
            message=snapshot.message,
            occurred_at=snapshot.occurred_at,
            request_id=snapshot.request_id,
            trace_id=snapshot.trace_id,
            authenticated_subject_id=snapshot.authenticated_subject_id,
            source_module=snapshot.source_module,
            source_component=snapshot.source_component,
            detail=AdminLogRecordDetailMapper.from_snapshot_detail(snapshot.detail),
        )


class AdminSecurityEventPayload(BaseModel):
    """
    管理员安全事件载荷。
    """

    model_config = ConfigDict(extra="forbid")

    event_id: str
    log_level: LogLevel
    log_message: str
    occurred_at: datetime
    request_id: str | None
    trace_id: str | None
    source_module: str
    source_component: str
    security_event: SecurityEventEnvelope

    @classmethod
    def from_snapshot(
        cls,
        snapshot: AdminLogRecordSnapshot,
    ) -> AdminSecurityEventPayload:
        """
        从管理员日志记录快照构建安全事件载荷。

        :param snapshot: 管理员日志记录快照。
        :type snapshot: AdminLogRecordSnapshot
        :returns: 管理员安全事件载荷。
        :rtype: AdminSecurityEventPayload
        :raises ValueError: 当快照不包含安全事件时抛出。
        """

        if snapshot.security_event is None:
            raise ValueError("安全事件快照必须包含 security_event。")
        return cls(
            event_id=snapshot.event_id,
            log_level=snapshot.level,
            log_message=snapshot.message,
            occurred_at=snapshot.occurred_at,
            request_id=snapshot.request_id,
            trace_id=snapshot.trace_id,
            source_module=snapshot.source_module,
            source_component=snapshot.source_component,
            security_event=snapshot.security_event,
        )


class AdminLogRecordListPayload(BaseModel):
    """
    管理员日志记录列表载荷。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["admin_log_record_list"] = ADMIN_LOG_RECORD_LIST_KIND
    schema_version: Literal["1.0"] = ADMIN_LOG_SCHEMA_VERSION
    records: list[AdminLogRecordPayload]

    @classmethod
    def from_snapshots(
        cls,
        snapshots: list[AdminLogRecordSnapshot],
    ) -> AdminLogRecordListPayload:
        """
        从管理员日志记录快照列表构建 HTTP 载荷。

        :param snapshots: 管理员日志记录快照列表。
        :type snapshots: list[AdminLogRecordSnapshot]
        :returns: 管理员日志记录列表载荷。
        :rtype: AdminLogRecordListPayload
        """

        return cls(
            records=[AdminLogRecordPayload.from_snapshot(snapshot) for snapshot in snapshots]
        )


class AdminSecurityEventListPayload(BaseModel):
    """
    管理员安全事件列表载荷。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["admin_security_event_list"] = ADMIN_SECURITY_EVENT_LIST_KIND
    schema_version: Literal["1.0"] = ADMIN_LOG_SCHEMA_VERSION
    events: list[AdminSecurityEventPayload]

    @classmethod
    def from_snapshots(
        cls,
        snapshots: list[AdminLogRecordSnapshot],
    ) -> AdminSecurityEventListPayload:
        """
        从管理员日志记录快照列表构建安全事件载荷。

        :param snapshots: 管理员日志记录快照列表。
        :type snapshots: list[AdminLogRecordSnapshot]
        :returns: 管理员安全事件列表载荷。
        :rtype: AdminSecurityEventListPayload
        """

        return cls(
            events=[
                AdminSecurityEventPayload.from_snapshot(snapshot)
                for snapshot in snapshots
                if snapshot.security_event is not None
            ]
        )


AdminLogRecordListDetail = Annotated[
    AdminLogRecordListPayload,
    Field(discriminator="kind"),
]
AdminSecurityEventListDetail = Annotated[
    AdminSecurityEventListPayload,
    Field(discriminator="kind"),
]


class AdminLogRecordListEnvelope(BaseModel):
    """
    管理员日志记录列表信封。
    """

    model_config = ConfigDict(extra="forbid")

    header: AdminLogHeader
    detail: AdminLogRecordListDetail

    @model_validator(mode="after")
    def validate_detail_contract(self) -> AdminLogRecordListEnvelope:
        """
        校验日志记录列表公共头与扩展字段一致。

        :returns: 当前信封。
        :rtype: AdminLogRecordListEnvelope
        """

        if self.header.kind.value != self.detail.kind:
            raise ValueError("日志记录列表 header.kind 必须与 detail.kind 一致。")
        if self.header.schema_version != self.detail.schema_version:
            raise ValueError("日志记录列表 schema_version 必须一致。")
        return self


class AdminSecurityEventListEnvelope(BaseModel):
    """
    管理员安全事件列表信封。
    """

    model_config = ConfigDict(extra="forbid")

    header: AdminLogHeader
    detail: AdminSecurityEventListDetail

    @model_validator(mode="after")
    def validate_detail_contract(self) -> AdminSecurityEventListEnvelope:
        """
        校验安全事件列表公共头与扩展字段一致。

        :returns: 当前信封。
        :rtype: AdminSecurityEventListEnvelope
        """

        if self.header.kind.value != self.detail.kind:
            raise ValueError("安全事件列表 header.kind 必须与 detail.kind 一致。")
        if self.header.schema_version != self.detail.schema_version:
            raise ValueError("安全事件列表 schema_version 必须一致。")
        return self
