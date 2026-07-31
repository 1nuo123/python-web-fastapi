"""日志与审计资源。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

from pydantic import TypeAdapter, ValidationError

from src.application.ports.admin_audit_query_port import (
    AdminAuditAction,
    AdminAuditEventPage,
    AdminAuditEventSnapshot,
    AdminAuditQuery,
    AdminAuditResult,
)
from src.application.ports.admin_log_query_port import (
    AdminLogRecordFilter,
    AdminLogRecordSnapshot,
    AdminSecurityEventFilter,
    AdminUnparsedLogDetail,
)
from src.core.http_contract.runtime_resource_contract import (
    RuntimeResourceStatus,
)
from src.core.logging_contract.log_event_contract import (
    AUDIT_CRITICAL_SECURITY_EVENT_TYPES,
    LOG_EVENT_SCHEMA_VERSION,
    LogDetailUnion,
    LogEventEnvelope,
    LogEventHeader,
    LogEventKind,
    LogLevel,
    LogPersistencePriority,
    ResourceLifecycleAction,
    ResourceLifecycleLogDetail,
    SecurityLogDetail,
)
from src.core.logging_contract.log_writer_contract import LogWriteReason
from src.core.security_contract.security_event_contract import (
    AdminIdentitySecurityEventDetail,
    SecurityEventEnvelope,
    SecurityEventType,
)
from src.infrastructure.logging.sensitive_text_redactor import SensitiveTextRedactor
from src.infrastructure.observability.prometheus_metrics_registry import (
    SecurityEventMetric,
)
from src.infrastructure.persistence.orm_model.app_log_record_orm_model import (
    AppLogRecordOrmModel,
)
from src.infrastructure.persistence.repository_impl.log_record_repository_impl import (
    LogRecordRepositoryImpl,
)
from src.infrastructure.resource_mount.shared_resource_constants import (
    ADMIN_AUDIT_ACTION_BY_OPERATION,
    ADMIN_AUDIT_OPERATION_BY_ACTION,
    ADMIN_AUDIT_OPERATION_NAMES,
    ADMIN_AUDIT_SUMMARY_TEMPLATE,
    LOG_DETAIL_UNPARSEABLE_SUMMARY,
)
from src.infrastructure.resource_mount.shared_resource_lifecycle import SharedResourceLifecycle
from src.infrastructure.task.failed_task_recorder import (
    TaskFailureRecord,
)

LOG_DETAIL_ADAPTER: TypeAdapter[LogDetailUnion] = TypeAdapter(LogDetailUnion)
AUDIT_CRITICAL_SECURITY_EVENT_TYPE_VALUES: frozenset[str] = frozenset(
    event_type.value for event_type in AUDIT_CRITICAL_SECURITY_EVENT_TYPES
)
SECURITY_EVENT_TYPE_VALUES: frozenset[str] = frozenset(
    event_type.value for event_type in SecurityEventType
)


class LoggingResourceFacade(SharedResourceLifecycle):
    """日志与审计资源门面。"""

    def list_admin_log_records(
        self,
        query_filter: AdminLogRecordFilter,
    ) -> list[AdminLogRecordSnapshot]:
        """
        查询管理员日志记录。
        """

        unit_of_work = self.create_unit_of_work()
        try:
            repository = LogRecordRepositoryImpl(unit_of_work.get_session())
            return [
                self._build_admin_log_snapshot(record)
                for record in repository.list_records(
                    limit=query_filter.limit,
                    level=query_filter.level,
                    event_kind=query_filter.event_kind,
                    request_id=query_filter.request_id,
                    trace_id=query_filter.trace_id,
                    occurred_from=query_filter.occurred_from,
                    occurred_to=query_filter.occurred_to,
                )
            ]
        finally:
            unit_of_work.dispose()

    def list_admin_security_events(
        self,
        query_filter: AdminSecurityEventFilter,
    ) -> list[AdminLogRecordSnapshot]:
        """
        查询管理员安全事件记录。
        """

        unit_of_work = self.create_unit_of_work()
        try:
            repository = LogRecordRepositoryImpl(unit_of_work.get_session())
            snapshots = [
                self._build_admin_log_snapshot(record)
                for record in repository.list_records(
                    limit=query_filter.limit,
                    event_kind=LogEventKind.SECURITY,
                    occurred_from=query_filter.occurred_from,
                    occurred_to=query_filter.occurred_to,
                    security_event_type=query_filter.event_type,
                    security_event_severity=query_filter.severity,
                    security_event_decision=query_filter.decision,
                )
            ]
            return [
                snapshot
                for snapshot in snapshots
                if self._matches_admin_security_filter(
                    snapshot=snapshot,
                    query_filter=query_filter,
                )
            ]
        finally:
            unit_of_work.dispose()

    def list_admin_audit_events(
        self,
        query: AdminAuditQuery,
    ) -> AdminAuditEventPage:
        """
        查询业务后台审计事件。
        """

        operation_names = self._resolve_admin_audit_operation_names(query.action)
        if operation_names is not None and len(operation_names) == 0:
            return AdminAuditEventPage(
                events=[],
                page_size=query.page_size,
                offset=query.offset,
                total=0,
            )
        unit_of_work = self.create_unit_of_work()
        try:
            repository = LogRecordRepositoryImpl(unit_of_work.get_session())
            records = repository.list_business_audit_records(
                page_size=query.page_size,
                offset=query.offset,
                operation_names=operation_names,
                actor_subject_id=query.actor_subject_id,
                target_kind=query.target_kind,
                target_id=query.target_id,
                occurred_from=query.occurred_from,
                occurred_to=query.occurred_to,
            )
            total = repository.count_business_audit_records(
                operation_names=operation_names,
                actor_subject_id=query.actor_subject_id,
                target_kind=query.target_kind,
                target_id=query.target_id,
                occurred_from=query.occurred_from,
                occurred_to=query.occurred_to,
            )
            return AdminAuditEventPage(
                events=[self._build_admin_audit_event_snapshot(record) for record in records],
                page_size=query.page_size,
                offset=query.offset,
                total=total,
            )
        finally:
            unit_of_work.dispose()

    def emit_log_event(self, event: LogEventEnvelope) -> None:
        """
        发送结构化日志事件。
        """

        if not self.read_runtime_bundle().settings.runtime.logging.enabled:
            return
        if self._logging_accessor.structured_log_handler is None:
            self._logging_accessor.pending_log_events.append(event)
            return
        self._logging_accessor.structured_log_handler.emit_event(event)

    def emit_security_event(self, event: SecurityEventEnvelope) -> None:
        """
        写入安全事件。

        审计类安全事件（管理员身份变更、安全配置拒绝）标记为审计关键优先级，
        经日志缓冲派发器绕过缓冲即时落库；同时挂接安全事件低基数指标。

        :param event: 安全事件信封。
        :type event: SecurityEventEnvelope
        :returns: 无返回值。
        :rtype: None
        """

        self.emit_log_event(
            self._log_event_builder.build_security_event(
                security_event=event,
                persistence_priority=self._resolve_security_persistence_priority(event),
            )
        )
        self._record_security_event_metric(event)

    def _resolve_security_persistence_priority(
        self,
        event: SecurityEventEnvelope,
    ) -> LogPersistencePriority:
        """
        解析安全事件的日志持久化优先级。

        :param event: 安全事件信封。
        :type event: SecurityEventEnvelope
        :returns: 审计关键事件返回 ``AUDIT_CRITICAL``，其余返回 ``STANDARD``。
        :rtype: LogPersistencePriority
        """

        if event.header.event_type in AUDIT_CRITICAL_SECURITY_EVENT_TYPE_VALUES:
            return LogPersistencePriority.AUDIT_CRITICAL
        return LogPersistencePriority.STANDARD

    def _record_security_event_metric(self, event: SecurityEventEnvelope) -> None:
        """
        记录安全事件指标。

        标签取值执行白名单策略：仅当事件类型属于 ``SecurityEventType`` 封闭枚举时打点，
        避免自由文本进入指标标签。

        :param event: 安全事件信封。
        :type event: SecurityEventEnvelope
        :returns: 无返回值。
        :rtype: None
        """

        metrics_registry = self.get_metrics_registry()
        if metrics_registry is None:
            return
        if event.header.event_type not in SECURITY_EVENT_TYPE_VALUES:
            return
        metrics_registry.record_security_event(
            SecurityEventMetric(
                event_type=SecurityEventType(event.header.event_type),
                decision=event.header.decision,
                severity=event.header.severity,
            )
        )

    def flush_runtime_logs(self, *, reason: LogWriteReason) -> None:
        """
        刷新运行时日志缓冲。

        :param reason: 日志写入原因。
        :type reason: LogWriteReason
        :returns: 无返回值。
        :rtype: None
        """

        self._flush_logs(reason=reason)

    def drain_pending_log_events(self) -> None:
        """
        刷出前置缓冲的日志事件。

        :returns: 无返回值。
        :rtype: None
        """

        self._drain_pending_log_events()

    def record_task_failure(self, record: TaskFailureRecord) -> None:
        """
        记录任务失败。

        :param record: 任务失败记录。
        :type record: TaskFailureRecord
        :returns: 无返回值。
        :rtype: None
        """

        self._failed_task_recorder.record(record)

    def _flush_logs(self, *, reason: LogWriteReason) -> None:
        """
        刷新日志缓冲区。
        """

        if self._log_buffer_dispatcher is None:
            return
        self._log_buffer_dispatcher.flush(reason)

    def _emit_resource_lifecycle_log(
        self,
        *,
        resource_name: str,
        lifecycle_action: ResourceLifecycleAction,
        resource_status: RuntimeResourceStatus,
        detail_text: str | None,
    ) -> None:
        """
        发送资源生命周期结构化日志。
        """

        event = self._log_event_builder.build_resource_lifecycle_event(
            resource_name=resource_name,
            lifecycle_action=lifecycle_action,
            resource_status=resource_status,
            detail_text=detail_text,
        )
        self.emit_log_event(event)

    def _record_task_failure(self, record: TaskFailureRecord) -> None:
        """
        统一记录任务失败并发送结构化日志。
        """

        event = self._log_event_builder.build_task_failure_event(record=record)
        self.emit_log_event(event)

    def _build_admin_log_snapshot(
        self,
        record: AppLogRecordOrmModel,
    ) -> AdminLogRecordSnapshot:
        """
        构建管理员日志记录快照。
        """

        log_event = self._build_admin_log_event(record)
        detail = (
            AdminUnparsedLogDetail(summary=LOG_DETAIL_UNPARSEABLE_SUMMARY)
            if log_event is None
            else self._redact_admin_log_detail(log_event.detail)
        )
        security_event = detail.security_event if isinstance(detail, SecurityLogDetail) else None
        return AdminLogRecordSnapshot(
            event_id=record.event_id,
            event_kind=LogEventKind(record.event_kind),
            schema_version=record.schema_version,
            level=LogLevel(record.level),
            message=record.message,
            occurred_at=record.occurred_at,
            request_id=record.request_id,
            trace_id=record.trace_id,
            authenticated_subject_id=record.authenticated_subject_id,
            source_module=record.source_module,
            source_component=record.source_component,
            detail=detail,
            security_event=security_event,
        )

    def _build_admin_log_event(
        self,
        record: AppLogRecordOrmModel,
    ) -> LogEventEnvelope | None:
        """
        按当前日志契约解析历史日志详情。
        """

        try:
            if record.schema_version != LOG_EVENT_SCHEMA_VERSION:
                return None
            return LogEventEnvelope(
                header=LogEventHeader(
                    schema_version=LOG_EVENT_SCHEMA_VERSION,
                    event_id=record.event_id,
                    occurred_at=record.occurred_at,
                    level=LogLevel(record.level),
                    kind=LogEventKind(record.event_kind),
                    message=record.message,
                    request_id=record.request_id,
                    trace_id=record.trace_id,
                    authenticated_subject_id=record.authenticated_subject_id,
                    source_module=record.source_module,
                    source_component=record.source_component,
                ),
                detail=LOG_DETAIL_ADAPTER.validate_python(record.detail_json),
            )
        except (ValidationError, ValueError):
            return None

    def _redact_admin_log_detail(self, detail: LogDetailUnion) -> LogDetailUnion:
        """
        对管理员日志详情执行查询侧兜底脱敏。
        """

        if isinstance(detail, ResourceLifecycleLogDetail):
            return detail.model_copy(
                update={
                    "detail": SensitiveTextRedactor().redact(detail.detail),
                }
            )
        return detail

    def _matches_admin_security_filter(
        self,
        *,
        snapshot: AdminLogRecordSnapshot,
        query_filter: AdminSecurityEventFilter,
    ) -> bool:
        """
        判断安全事件是否命中过滤条件。
        """

        security_event = snapshot.security_event
        if security_event is None:
            return False
        if (
            query_filter.event_type is not None
            and security_event.header.event_type != query_filter.event_type.value
        ):
            return False
        if (
            query_filter.severity is not None
            and security_event.header.severity != query_filter.severity
        ):
            return False
        if (
            query_filter.decision is not None
            and security_event.header.decision != query_filter.decision
        ):
            return False
        return True

    def _resolve_admin_audit_operation_names(
        self,
        action: AdminAuditAction | None,
    ) -> list[str]:
        """
        解析业务审计动作对应的身份操作名称。
        """

        if action is None:
            return list(ADMIN_AUDIT_OPERATION_NAMES)
        return list(ADMIN_AUDIT_OPERATION_BY_ACTION.get(action, ()))

    def _build_admin_audit_event_snapshot(
        self,
        record: AppLogRecordOrmModel,
    ) -> AdminAuditEventSnapshot:
        """
        构建业务审计事件快照。
        """

        log_event = self._build_admin_log_event(record)
        if log_event is None or not isinstance(log_event.detail, SecurityLogDetail):
            raise ValueError("业务审计日志记录无法解析为安全日志。")
        audit_detail = log_event.detail.security_event.detail
        if not isinstance(audit_detail, AdminIdentitySecurityEventDetail):
            raise ValueError("业务审计日志记录缺少管理员身份变更详情。")
        action = ADMIN_AUDIT_ACTION_BY_OPERATION.get(audit_detail.operation_name)
        if action is None:
            raise ValueError("业务审计日志记录不属于业务审计动作白名单。")
        return AdminAuditEventSnapshot(
            event_id=record.event_id,
            action=action,
            actor_subject_id=audit_detail.actor_subject_id,
            target_kind=audit_detail.target_kind,
            target_id=audit_detail.target_id,
            result=AdminAuditResult.SUCCESS,
            occurred_at=record.occurred_at,
            summary=ADMIN_AUDIT_SUMMARY_TEMPLATE.format(
                actor_subject_id=audit_detail.actor_subject_id,
                target_kind=audit_detail.target_kind,
                target_id=audit_detail.target_id,
                action=action.value,
            ),
        )

    def _on_task_failure_recorded(self, record: TaskFailureRecord) -> None:
        """
        处理失败任务记录事件。
        """

        self._record_task_failure(record)

    def _drain_pending_log_events(self) -> None:
        """
        刷出前置缓冲的日志事件。
        """

        if self._logging_accessor.structured_log_handler is None:
            return
        pending_events = list(self._logging_accessor.pending_log_events)
        self._logging_accessor.pending_log_events.clear()
        for event in pending_events:
            self._logging_accessor.structured_log_handler.emit_event(event)
