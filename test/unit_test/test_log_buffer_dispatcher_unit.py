"""
日志缓冲派发器审计关键路径单元测试模块。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from src.core.logging_contract.log_event_contract import (
    AccessLogDetail,
    LogEventEnvelope,
    LogEventHeader,
    LogEventKind,
    LogLevel,
    LogPersistencePriority,
)
from src.core.logging_contract.log_writer_contract import (
    LogWriteReason,
    LogWriteRequest,
    LogWriteResult,
)
from src.infrastructure.logging.log_buffer_dispatcher import LogBufferDispatcher
from src.infrastructure.observability.prometheus_metrics_registry import (
    LOG_BUFFER_FLUSH_TOTAL_NAME,
    LOG_BUFFER_PENDING_ITEMS_NAME,
    PrometheusMetricsRegistry,
)

LOGGER_CRITICAL_NAME = "test_log_buffer_dispatcher_critical"
LOGGER_CRITICAL_FAILURE_NAME = "test_log_buffer_dispatcher_critical_failure"
LOGGER_STANDARD_NAME = "test_log_buffer_dispatcher_standard"
LOGGER_SNAPSHOT_NAME = "test_log_buffer_dispatcher_snapshot"
LOGGER_METRICS_NAME = "test_log_buffer_dispatcher_metrics"
LOGGER_INTERNAL_NAME = "test_log_buffer_dispatcher_internal_capture"
EVENT_ID = "event-critical-1"
REQUEST_ID = "request-1"
TRACE_ID = "trace-1"
SUBJECT_ID = "user-1"
SOURCE_MODULE = "infrastructure"
SOURCE_COMPONENT = "security_protection"
REQUEST_PATH = "/admin/users"
REQUEST_METHOD = "POST"
LOG_MESSAGE = "审计关键事件。"
HTTP_OK_STATUS = 200
ELAPSED_MILLISECONDS = 1.0
BUFFER_MAX_ITEMS = 10
MAX_BATCH_SIZE_LARGE = 10
FLUSH_INTERVAL_SECONDS = 100
EMPTY_FAILED_COUNT = 0
FAILED_WRITE_COUNT = 1
FAILED_WRITER_REASON = "数据库写入失败。"
EXPECTED_SINGLE_REQUEST_COUNT = 1
EXPECTED_CRITICAL_BATCH_SIZE = 1
EXPECTED_PENDING_AFTER_STANDARD_EMIT = 1
AUDIT_CRITICAL_FLUSH_FAILED_SAMPLE = (
    f'{LOG_BUFFER_FLUSH_TOTAL_NAME}{{failed="true",reason="audit_critical"}}'
)


class RecordingWriter:
    """
    记录写入请求的日志写入器测试替身。
    """

    def __init__(self) -> None:
        """
        初始化记录写入器。
        """

        self.requests: list[LogWriteRequest] = []

    def write_batch(self, request: LogWriteRequest) -> LogWriteResult:
        """
        记录写入请求并返回成功结果。
        """

        self.requests.append(request)
        return LogWriteResult(
            written_count=len(request.events),
            failed_count=EMPTY_FAILED_COUNT,
            degraded_to_stdout=False,
            failure_reason=None,
        )


class FailingDegradedWriter:
    """
    写入失败且触发 stdout 降级的日志写入器测试替身。
    """

    def __init__(self) -> None:
        """
        初始化失败写入器。
        """

        self.requests: list[LogWriteRequest] = []

    def write_batch(self, request: LogWriteRequest) -> LogWriteResult:
        """
        返回写入失败且已降级 stdout 的结果。
        """

        self.requests.append(request)
        return LogWriteResult(
            written_count=0,
            failed_count=len(request.events),
            degraded_to_stdout=True,
            failure_reason=FAILED_WRITER_REASON,
        )


class CapturingLogHandler(logging.Handler):
    """
    捕获日志记录的 handler。
    """

    def __init__(self) -> None:
        """
        初始化捕获 handler。
        """

        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        """
        保存日志记录。
        """

        self.records.append(record)


class TestLogBufferDispatcherUnit:
    """
    日志缓冲派发器审计关键路径单元测试集合。
    """

    def test_emit_when_audit_critical_should_bypass_buffer_and_write_sync(self) -> None:
        """
        验证审计关键事件绕过缓冲并在 emit 返回前同步落库。
        """

        writer = RecordingWriter()
        dispatcher = self._build_dispatcher(writer=writer, logger_name=LOGGER_CRITICAL_NAME)
        try:
            dispatcher.emit(self._build_event(LogPersistencePriority.AUDIT_CRITICAL))

            assert len(writer.requests) == EXPECTED_SINGLE_REQUEST_COUNT
            assert writer.requests[0].reason == LogWriteReason.AUDIT_CRITICAL
            assert len(writer.requests[0].events) == EXPECTED_CRITICAL_BATCH_SIZE
            snapshot = dispatcher.read_audit_write_failure_counter()
            assert snapshot.pending_items == 0
        finally:
            dispatcher.shutdown()

    def test_emit_when_standard_priority_should_keep_buffered_path(self) -> None:
        """
        验证标准优先级事件仍走缓冲路径且不即时写库。
        """

        writer = RecordingWriter()
        dispatcher = self._build_dispatcher(writer=writer, logger_name=LOGGER_STANDARD_NAME)
        try:
            dispatcher.emit(self._build_event(LogPersistencePriority.STANDARD))

            assert len(writer.requests) == 0
            snapshot = dispatcher.read_audit_write_failure_counter()
            assert snapshot.pending_items == EXPECTED_PENDING_AFTER_STANDARD_EMIT

            flush_result = dispatcher.flush(LogWriteReason.MANUAL)

            assert flush_result.written_count == EXPECTED_SINGLE_REQUEST_COUNT
            assert writer.requests[0].reason == LogWriteReason.MANUAL
        finally:
            dispatcher.shutdown()

    def test_audit_critical_write_failure_should_increase_counter_and_degrade(self) -> None:
        """
        验证审计关键写失败递增失败计数、写内部日志且降级标记透传。
        """

        internal_logger = logging.getLogger(LOGGER_INTERNAL_NAME)
        internal_handler = CapturingLogHandler()
        internal_logger.handlers.clear()
        internal_logger.propagate = False
        internal_logger.addHandler(internal_handler)
        writer = FailingDegradedWriter()
        dispatcher = LogBufferDispatcher(
            writer=writer,
            logger=logging.getLogger(LOGGER_CRITICAL_FAILURE_NAME),
            internal_logger=internal_logger,
            buffer_max_items=BUFFER_MAX_ITEMS,
            flush_interval_seconds=FLUSH_INTERVAL_SECONDS,
            max_batch_size=MAX_BATCH_SIZE_LARGE,
        )
        try:
            dispatcher.emit(self._build_event(LogPersistencePriority.AUDIT_CRITICAL))

            snapshot = dispatcher.read_audit_write_failure_counter()
            assert snapshot.failed_count == FAILED_WRITE_COUNT
            assert len(internal_handler.records) == EXPECTED_SINGLE_REQUEST_COUNT
            assert len(writer.requests) == EXPECTED_SINGLE_REQUEST_COUNT
        finally:
            dispatcher.shutdown()
            internal_logger.handlers.clear()

    def test_snapshot_should_accumulate_multiple_failures(self) -> None:
        """
        验证失败计数随多次审计关键写失败累加。
        """

        dispatcher = LogBufferDispatcher(
            writer=FailingDegradedWriter(),
            logger=logging.getLogger(LOGGER_SNAPSHOT_NAME),
            buffer_max_items=BUFFER_MAX_ITEMS,
            flush_interval_seconds=FLUSH_INTERVAL_SECONDS,
            max_batch_size=MAX_BATCH_SIZE_LARGE,
        )
        try:
            dispatcher.emit(self._build_event(LogPersistencePriority.AUDIT_CRITICAL))
            dispatcher.emit(self._build_event(LogPersistencePriority.AUDIT_CRITICAL))

            snapshot = dispatcher.read_audit_write_failure_counter()
            assert snapshot.failed_count == FAILED_WRITE_COUNT * 2
        finally:
            dispatcher.shutdown()

    def test_metrics_registry_should_receive_flush_and_pending_samples(self) -> None:
        """
        验证刷盘结果回调挂接指标注册器并输出刷盘与积压样本。
        """

        metrics_registry = PrometheusMetricsRegistry()
        dispatcher = LogBufferDispatcher(
            writer=FailingDegradedWriter(),
            logger=logging.getLogger(LOGGER_METRICS_NAME),
            buffer_max_items=BUFFER_MAX_ITEMS,
            flush_interval_seconds=FLUSH_INTERVAL_SECONDS,
            max_batch_size=MAX_BATCH_SIZE_LARGE,
            metrics_registry=metrics_registry,
        )
        try:
            dispatcher.emit(self._build_event(LogPersistencePriority.AUDIT_CRITICAL))
            dispatcher.emit(self._build_event(LogPersistencePriority.STANDARD))

            metrics_text = metrics_registry.render().decode()
            assert AUDIT_CRITICAL_FLUSH_FAILED_SAMPLE in metrics_text
            assert LOG_BUFFER_PENDING_ITEMS_NAME in metrics_text
        finally:
            dispatcher.shutdown()

    def _build_dispatcher(
        self,
        *,
        writer: RecordingWriter,
        logger_name: str,
    ) -> LogBufferDispatcher:
        """
        构建大缓冲窗口的日志缓冲派发器。
        """

        return LogBufferDispatcher(
            writer=writer,
            logger=logging.getLogger(logger_name),
            buffer_max_items=BUFFER_MAX_ITEMS,
            flush_interval_seconds=FLUSH_INTERVAL_SECONDS,
            max_batch_size=MAX_BATCH_SIZE_LARGE,
        )

    def _build_event(self, priority: LogPersistencePriority) -> LogEventEnvelope:
        """
        构建指定持久化优先级的日志事件。
        """

        return LogEventEnvelope(
            header=LogEventHeader(
                event_id=EVENT_ID,
                occurred_at=datetime.now(UTC),
                level=LogLevel.INFO,
                kind=LogEventKind.ACCESS,
                persistence_priority=priority,
                message=LOG_MESSAGE,
                request_id=REQUEST_ID,
                trace_id=TRACE_ID,
                authenticated_subject_id=SUBJECT_ID,
                source_module=SOURCE_MODULE,
                source_component=SOURCE_COMPONENT,
            ),
            detail=AccessLogDetail(
                request_path=REQUEST_PATH,
                request_method=REQUEST_METHOD,
                status_code=HTTP_OK_STATUS,
                elapsed_milliseconds=ELAPSED_MILLISECONDS,
                client_ip=None,
                user_agent=None,
                route_name=None,
            ),
        )
