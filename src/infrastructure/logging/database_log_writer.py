"""
数据库日志写入器模块。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy.exc import SQLAlchemyError

from src.core.logging_contract.log_event_contract import LogEventEnvelope
from src.core.logging_contract.log_writer_contract import LogWriteRequest, LogWriteResult
from src.infrastructure.logging.sensitive_text_redactor import SensitiveTextRedactor
from src.infrastructure.persistence.orm_model.app_log_record_orm_model import (
    AppLogRecordOrmModel,
)
from src.infrastructure.persistence.repository_impl.log_record_repository_impl import (
    LogRecordRepositoryImpl,
)
from src.infrastructure.resource_slot.shared_db_session_manager import (
    SharedDbSessionManager,
)


@dataclass(slots=True)
class DatabaseLogWriter:
    """
    数据库日志写入器。
    """

    session_manager: SharedDbSessionManager
    logger: logging.Logger
    fallback_to_stdout: bool
    sensitive_text_redactor: SensitiveTextRedactor = field(default_factory=SensitiveTextRedactor)

    def write_batch(self, request: LogWriteRequest) -> LogWriteResult:
        """
        批量写入日志事件。

        :param request: 日志写入请求。
        :type request: LogWriteRequest
        :returns: 日志写入结果。
        :rtype: LogWriteResult
        """

        unit_of_work = self.session_manager.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            repository = LogRecordRepositoryImpl(session)
            repository.add_records([self._build_record(event) for event in request.events])
            unit_of_work.commit()
            return LogWriteResult(
                written_count=len(request.events),
                failed_count=0,
                degraded_to_stdout=False,
                failure_reason=None,
            )
        except SQLAlchemyError as exc:
            unit_of_work.rollback()
            self._fallback_stdout(
                events=request.events,
                failure_reason=str(exc),
            )
            return LogWriteResult(
                written_count=0,
                failed_count=len(request.events),
                degraded_to_stdout=self.fallback_to_stdout,
                failure_reason=str(exc),
            )
        finally:
            unit_of_work.dispose()

    def _build_record(self, event: LogEventEnvelope) -> AppLogRecordOrmModel:
        """
        构建日志 ORM 记录。

        :param event: 日志事件信封。
        :type event: LogEventEnvelope
        :returns: ORM 记录对象。
        :rtype: AppLogRecordOrmModel
        """

        detail_mapping = event.detail.model_dump(mode="json")
        return AppLogRecordOrmModel(
            event_id=event.header.event_id,
            event_kind=event.header.kind.value,
            schema_version=event.header.schema_version,
            level=event.header.level.value,
            message=event.header.message,
            occurred_at=event.header.occurred_at,
            request_id=event.header.request_id,
            trace_id=event.header.trace_id,
            authenticated_subject_id=event.header.authenticated_subject_id,
            source_module=event.header.source_module,
            source_component=event.header.source_component,
            detail_json=detail_mapping,
        )

    def _fallback_stdout(
        self,
        *,
        events: list[LogEventEnvelope],
        failure_reason: str,
    ) -> None:
        """
        在数据库写入失败时执行保底输出。

        :param events: 待输出的日志事件列表。
        :type events: list[LogEventEnvelope]
        :param failure_reason: 失败原因。
        :type failure_reason: str
        :returns: 无返回值。
        :rtype: None
        """

        if not self.fallback_to_stdout:
            return
        for event in events:
            redacted_event_json = self.sensitive_text_redactor.redact(event.model_dump_json())
            redacted_failure_reason = self.sensitive_text_redactor.redact(failure_reason)
            self.logger.error(
                "数据库日志写入失败，已降级输出：%s | 原因：%s | 事件：%s",
                event.header.message,
                redacted_failure_reason,
                redacted_event_json,
            )
