"""
日志事件构造器模块。
"""

from __future__ import annotations

import traceback
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

from starlette.requests import HTTPConnection

from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.http_contract.runtime_resource_contract import RuntimeResourceStatus
from src.core.logging_contract.log_event_contract import (
    AccessLogDetail,
    ExceptionLogDetail,
    LogEventEnvelope,
    LogEventHeader,
    LogEventKind,
    LogLevel,
    LogPersistencePriority,
    RequestLogContext,
    ResourceLifecycleAction,
    ResourceLifecycleLogDetail,
    SecurityLogDetail,
    StreamAccessLogDetail,
    TaskFailureLogDetail,
)
from src.core.security_contract.security_event_contract import (
    SecurityEventEnvelope,
    SecurityEventSeverity,
)
from src.core.stream_contract.stream_event_contract import StreamCloseReason, StreamTransport
from src.infrastructure.logging.sensitive_text_redactor import SensitiveTextRedactor
from src.infrastructure.security.client_ip_resolver import ClientIpResolver
from src.infrastructure.task.failed_task_recorder import TaskFailureRecord

SOURCE_MODULE_INFRASTRUCTURE = "infrastructure"
SOURCE_COMPONENT_ACCESS_LOG = "access_log_middleware"
SOURCE_COMPONENT_EXCEPTION_PRESENTER = "fastapi_exception_presenter"
SOURCE_COMPONENT_SHARED_RESOURCE_MOUNT = "shared_resource_mount"
SOURCE_COMPONENT_SECURITY_PROTECTION = "security_protection"
SOURCE_COMPONENT_TASK_RUNTIME = "task_runtime"
SECURITY_EVENT_REDACTION_FAILED_MESSAGE = "安全事件脱敏后契约校验失败。"
SECURITY_EVENT_LOG_MESSAGE = "安全事件：{event_type}"
WEBSOCKET_REQUEST_METHOD = "WEBSOCKET"


@dataclass(slots=True)
class LogEventBuilder:
    """
    日志事件构造器。
    """

    sensitive_text_redactor: SensitiveTextRedactor = field(default_factory=SensitiveTextRedactor)
    client_ip_resolver: ClientIpResolver = field(default_factory=ClientIpResolver)

    def build_request_context(self, request: HTTPConnection) -> RequestLogContext:
        """
        构建请求日志上下文。
        """

        request_scope = getattr(request.state, "request_scope", None)
        if request_scope is None:
            request_id = "request-scope-missing"
            trace_id = None
            authenticated_subject_id = None
            request_path = request.url.path
            request_method = str(request.scope.get("method", WEBSOCKET_REQUEST_METHOD))
        else:
            request_id = request_scope.request_id
            trace_id = request_scope.trace_id
            authenticated_subject_id = request_scope.authenticated_subject_id
            request_path = request_scope.request_path
            request_method = request_scope.request_method
        client_ip = self.client_ip_resolver.resolve_client_ip(request)
        user_agent = request.headers.get("user-agent")
        return RequestLogContext(
            request_id=request_id,
            trace_id=trace_id,
            authenticated_subject_id=authenticated_subject_id,
            request_path=request_path,
            request_method=request_method,
            client_ip=client_ip,
            user_agent=user_agent,
        )

    def build_access_event(
        self,
        *,
        request_context: RequestLogContext,
        status_code: int,
        elapsed_milliseconds: float,
        route_name: str | None = None,
    ) -> LogEventEnvelope:
        """
        构建访问日志事件。
        """

        detail = AccessLogDetail(
            request_path=request_context.request_path,
            request_method=request_context.request_method,
            status_code=status_code,
            elapsed_milliseconds=elapsed_milliseconds,
            client_ip=request_context.client_ip,
            user_agent=request_context.user_agent,
            route_name=route_name,
        )
        return self._build_event(
            level=LogLevel.INFO,
            kind=LogEventKind.ACCESS,
            message=f"请求完成：{request_context.request_method} {request_context.request_path}",
            request_context=request_context,
            source_component=SOURCE_COMPONENT_ACCESS_LOG,
            detail=detail,
        )

    def build_stream_access_event(
        self,
        *,
        request_context: RequestLogContext,
        status_code: int,
        elapsed_milliseconds: float,
        operation_name: str,
        transport: StreamTransport,
        event_count: int,
        close_reason: StreamCloseReason,
        subject_digest: str,
    ) -> LogEventEnvelope:
        """构建不含业务正文与主体原文的流访问日志事件。"""

        detail = StreamAccessLogDetail(
            request_path=request_context.request_path,
            request_method=request_context.request_method,
            status_code=status_code,
            elapsed_milliseconds=elapsed_milliseconds,
            operation_name=operation_name,
            transport=transport,
            event_count=event_count,
            close_reason=close_reason,
            subject_digest=subject_digest,
        )
        sanitized_context = request_context.model_copy(update={"authenticated_subject_id": None})
        return self._build_event(
            level=LogLevel.INFO,
            kind=LogEventKind.STREAM_ACCESS,
            message=f"流连接完成：{operation_name} {transport.value}",
            request_context=sanitized_context,
            source_component=SOURCE_COMPONENT_ACCESS_LOG,
            detail=detail,
        )

    def build_exception_event(
        self,
        *,
        request_context: RequestLogContext,
        exception: Exception,
        status_code: int,
        error_code: str,
        include_traceback: bool,
    ) -> LogEventEnvelope:
        """
        构建异常日志事件。
        """

        raw_detail_text = (
            exception.detail if isinstance(exception, HttpFaultException) else str(exception)
        )
        raw_traceback_text = (
            "".join(
                traceback.format_exception(
                    type(exception),
                    exception,
                    exception.__traceback__,
                )
            )
            if include_traceback
            else None
        )
        detail = ExceptionLogDetail(
            request_path=request_context.request_path,
            request_method=request_context.request_method,
            status_code=status_code,
            error_code=error_code,
            exception_type=type(exception).__name__,
            detail=self.sensitive_text_redactor.redact(raw_detail_text),
            traceback_text=self.sensitive_text_redactor.redact(raw_traceback_text),
        )
        level = LogLevel.ERROR if status_code >= 500 else LogLevel.WARNING
        return self._build_event(
            level=level,
            kind=LogEventKind.EXCEPTION,
            message=f"请求异常：{request_context.request_method} {request_context.request_path}",
            request_context=request_context,
            source_component=SOURCE_COMPONENT_EXCEPTION_PRESENTER,
            detail=detail,
        )

    def build_resource_lifecycle_event(
        self,
        *,
        resource_name: str,
        lifecycle_action: ResourceLifecycleAction,
        resource_status: RuntimeResourceStatus,
        detail_text: str | None,
    ) -> LogEventEnvelope:
        """
        构建资源生命周期日志事件。
        """

        detail = ResourceLifecycleLogDetail(
            resource_name=resource_name,
            lifecycle_action=lifecycle_action,
            resource_status=resource_status,
            detail=self.sensitive_text_redactor.redact(detail_text),
        )
        level = LogLevel.ERROR if resource_status == RuntimeResourceStatus.FAILED else LogLevel.INFO
        return self._build_event(
            level=level,
            kind=LogEventKind.RESOURCE_LIFECYCLE,
            message=f"资源状态变更：{resource_name} -> {resource_status.value}",
            request_context=None,
            source_component=SOURCE_COMPONENT_SHARED_RESOURCE_MOUNT,
            detail=detail,
        )

    def build_task_failure_event(
        self,
        *,
        record: TaskFailureRecord,
    ) -> LogEventEnvelope:
        """
        构建任务失败日志事件。
        """

        detail = TaskFailureLogDetail(
            task_id=record.task_id,
            job_kind=record.job_kind,
            backend=record.backend.value,
            stage=record.stage.value,
            retry_count=record.retry_count,
            queue_name=record.queue_name,
            payload_kind=record.payload_kind,
            request_id=record.request_id,
            trace_id=record.trace_id,
            deduplication_key=record.deduplication_key,
            attempt_count=record.attempt_count,
            detail=self.sensitive_text_redactor.redact(record.last_error or record.message),
        )
        return self._build_event(
            level=LogLevel.ERROR,
            kind=LogEventKind.TASK_FAILURE,
            message=f"任务失败：{record.job_kind} {record.stage.value}",
            request_context=None,
            source_component=SOURCE_COMPONENT_TASK_RUNTIME,
            detail=detail,
        )

    def build_security_event(
        self,
        *,
        security_event: SecurityEventEnvelope,
        persistence_priority: LogPersistencePriority = LogPersistencePriority.STANDARD,
    ) -> LogEventEnvelope:
        """
        构建安全日志事件。

        :param security_event: 安全事件信封。
        :type security_event: SecurityEventEnvelope
        :param persistence_priority: 日志持久化优先级；审计关键事件应传入
            ``LogPersistencePriority.AUDIT_CRITICAL`` 以触发即时落库。
        :type persistence_priority: LogPersistencePriority
        :returns: 日志事件信封。
        :rtype: LogEventEnvelope
        :raises ValueError: 当安全事件脱敏后无法通过契约校验时抛出。
        """

        redacted_event_json = self.sensitive_text_redactor.redact(security_event.model_dump_json())
        try:
            safe_security_event = SecurityEventEnvelope.model_validate_json(
                redacted_event_json or security_event.model_dump_json()
            )
        except Exception as exc:
            raise ValueError(SECURITY_EVENT_REDACTION_FAILED_MESSAGE) from exc
        detail = SecurityLogDetail(security_event=safe_security_event)
        request_context = RequestLogContext(
            request_id=safe_security_event.header.request_id,
            trace_id=safe_security_event.header.trace_id,
            request_path=safe_security_event.header.path,
            request_method=safe_security_event.header.method,
        )
        return self._build_event(
            level=self._map_security_level(safe_security_event.header.severity),
            kind=LogEventKind.SECURITY,
            message=SECURITY_EVENT_LOG_MESSAGE.format(
                event_type=safe_security_event.header.event_type
            ),
            request_context=request_context,
            source_component=SOURCE_COMPONENT_SECURITY_PROTECTION,
            detail=detail,
            persistence_priority=persistence_priority,
        )

    def _map_security_level(self, severity: SecurityEventSeverity) -> LogLevel:
        """
        映射安全事件等级到日志等级。
        """

        if severity == SecurityEventSeverity.HIGH:
            return LogLevel.ERROR
        if severity == SecurityEventSeverity.WARNING:
            return LogLevel.WARNING
        return LogLevel.INFO

    def _build_event(
        self,
        *,
        level: LogLevel,
        kind: LogEventKind,
        message: str,
        request_context: RequestLogContext | None,
        source_component: str,
        detail: AccessLogDetail
        | StreamAccessLogDetail
        | ExceptionLogDetail
        | ResourceLifecycleLogDetail
        | TaskFailureLogDetail
        | SecurityLogDetail,
        persistence_priority: LogPersistencePriority = LogPersistencePriority.STANDARD,
    ) -> LogEventEnvelope:
        """
        构建统一日志事件信封。
        """

        return LogEventEnvelope(
            header=LogEventHeader(
                event_id=str(uuid4()),
                occurred_at=datetime.now(UTC),
                level=level,
                kind=kind,
                persistence_priority=persistence_priority,
                message=message,
                request_id=None if request_context is None else request_context.request_id,
                trace_id=None if request_context is None else request_context.trace_id,
                authenticated_subject_id=(
                    None if request_context is None else request_context.authenticated_subject_id
                ),
                source_module=SOURCE_MODULE_INFRASTRUCTURE,
                source_component=source_component,
            ),
            detail=detail,
        )
