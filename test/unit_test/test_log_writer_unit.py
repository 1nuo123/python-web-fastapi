"""
测试日志写入单元测试模块。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from pytest import MonkeyPatch

from src.core.logging_contract.log_event_contract import (
    AccessLogDetail,
    LogEventEnvelope,
    LogEventHeader,
    LogEventKind,
    LogLevel,
)
from src.core.logging_contract.log_writer_contract import (
    LogWriteReason,
    LogWriteRequest,
    LogWriteResult,
)
from src.infrastructure.logging import log_buffer_dispatcher as log_buffer_dispatcher_module
from src.infrastructure.logging.log_buffer_dispatcher import LogBufferDispatcher

LOGGER_BATCH_NAME = "test_log_buffer_dispatcher"
LOGGER_MANUAL_NAME = "test_log_buffer_dispatcher_manual"
LOGGER_INTERVAL_NAME = "test_log_buffer_dispatcher_interval"
LOGGER_FAILURE_RUNTIME_NAME = "test_log_buffer_dispatcher_failure_runtime"
LOGGER_FAILURE_INTERNAL_NAME = "test_log_buffer_dispatcher_failure_internal"
LOGGER_SHUTDOWN_NAME = "test_log_buffer_dispatcher_shutdown"
EVENT_ID = "event-1"
REQUEST_ID = "request-1"
TRACE_ID = "trace-1"
SUBJECT_ID = "user-1"
SOURCE_MODULE = "infrastructure"
SOURCE_COMPONENT = "access_log_middleware"
REQUEST_PATH = "/health/live"
REQUEST_METHOD = "GET"
CLIENT_IP = "127.0.0.1"
USER_AGENT = "pytest"
ROUTE_NAME = "health_live"
LOG_MESSAGE = "请求完成。"
HTTP_OK_STATUS = 200
ELAPSED_MILLISECONDS = 1.0
EMPTY_FAILED_COUNT = 0
INITIAL_LOG_EPOCH_SECONDS = 1000.0
INTERVAL_FLUSH_EPOCH_SECONDS = 1101.0
BUFFER_MAX_ITEMS = 10
MAX_BATCH_SIZE_ONE = 1
MAX_BATCH_SIZE_LARGE = 10
FLUSH_INTERVAL_SECONDS = 100
FAILED_WRITE_COUNT = 1
FAILED_WRITER_REASON = "数据库写入失败。"
SHUTDOWN_EXPECTED_REQUEST_COUNT = 1


class FakeWriter:
    """
    伪日志写入器。
    """

    def __init__(self) -> None:
        """
        初始化伪日志写入器。
        """

        self.requests: list[LogWriteRequest] = []

    def write_batch(self, request: LogWriteRequest) -> LogWriteResult:
        """
        写入批次。
        """

        self.requests.append(request)
        return LogWriteResult(
            written_count=len(request.events),
            failed_count=EMPTY_FAILED_COUNT,
            degraded_to_stdout=False,
            failure_reason=None,
        )


class FailingWriter:
    """
    写入失败的日志写入器测试替身。
    """

    def write_batch(self, request: LogWriteRequest) -> LogWriteResult:
        """
        返回写入失败结果。
        """

        return LogWriteResult(
            written_count=len(request.events) - FAILED_WRITE_COUNT,
            failed_count=FAILED_WRITE_COUNT,
            degraded_to_stdout=False,
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


class TestLogWriterUnit:
    """
    测试日志写入单元测试集合，用于组织同一主题下的测试场景。
    """

    def test_log_buffer_dispatcher_should_flush_when_batch_reached(self) -> None:
        """
        验证日志缓冲派发器应在达到批量阈值时刷盘。
        """

        fake_writer = FakeWriter()
        logger = logging.getLogger(LOGGER_BATCH_NAME)
        dispatcher = LogBufferDispatcher(
            writer=fake_writer,
            logger=logger,
            buffer_max_items=BUFFER_MAX_ITEMS,
            flush_interval_seconds=FLUSH_INTERVAL_SECONDS,
            max_batch_size=MAX_BATCH_SIZE_ONE,
        )
        try:
            dispatcher.emit(self._build_event())
            dispatcher.flush(LogWriteReason.MANUAL)

            assert len(fake_writer.requests) == 1
        finally:
            dispatcher.shutdown()

    def test_log_buffer_dispatcher_should_flush_manually(self) -> None:
        """
        验证日志缓冲派发器应支持手动刷盘。
        """

        fake_writer = FakeWriter()
        logger = logging.getLogger(LOGGER_MANUAL_NAME)
        dispatcher = LogBufferDispatcher(
            writer=fake_writer,
            logger=logger,
            buffer_max_items=BUFFER_MAX_ITEMS,
            flush_interval_seconds=FLUSH_INTERVAL_SECONDS,
            max_batch_size=MAX_BATCH_SIZE_LARGE,
        )
        try:
            dispatcher.emit(self._build_event())
            dispatcher.flush(LogWriteReason.MANUAL)

            assert len(fake_writer.requests) == 1
        finally:
            dispatcher.shutdown()

    def test_log_buffer_dispatcher_should_flush_interval_on_next_emit(
        self,
        monkeypatch: MonkeyPatch,
    ) -> None:
        """
        验证 flush_interval_seconds 语义为下一条日志触发刷盘。
        """

        fake_writer = FakeWriter()
        logger = logging.getLogger(LOGGER_INTERVAL_NAME)
        dispatcher = LogBufferDispatcher(
            writer=fake_writer,
            logger=logger,
            buffer_max_items=BUFFER_MAX_ITEMS,
            flush_interval_seconds=FLUSH_INTERVAL_SECONDS,
            max_batch_size=MAX_BATCH_SIZE_LARGE,
        )
        dispatcher._last_flush_epoch = INITIAL_LOG_EPOCH_SECONDS
        monkeypatch.setattr(
            log_buffer_dispatcher_module.time,
            "time",
            lambda: INTERVAL_FLUSH_EPOCH_SECONDS,
        )

        try:
            dispatcher.emit(self._build_event())
            dispatcher.flush(LogWriteReason.MANUAL)

            assert len(fake_writer.requests) == 1
            assert fake_writer.requests[0].reason == LogWriteReason.INTERVAL
        finally:
            dispatcher.shutdown()

    def test_log_buffer_dispatcher_should_use_internal_logger_on_write_failure(
        self,
    ) -> None:
        """
        验证刷盘失败只写独立内部 logger，避免回灌运行时 logger。
        """

        runtime_logger = logging.getLogger(LOGGER_FAILURE_RUNTIME_NAME)
        internal_logger = logging.getLogger(LOGGER_FAILURE_INTERNAL_NAME)
        runtime_handler = CapturingLogHandler()
        internal_handler = CapturingLogHandler()
        runtime_logger.handlers.clear()
        internal_logger.handlers.clear()
        runtime_logger.propagate = False
        internal_logger.propagate = False
        runtime_logger.addHandler(runtime_handler)
        internal_logger.addHandler(internal_handler)
        try:
            dispatcher = LogBufferDispatcher(
                writer=FailingWriter(),
                logger=runtime_logger,
                internal_logger=internal_logger,
                buffer_max_items=BUFFER_MAX_ITEMS,
                flush_interval_seconds=FLUSH_INTERVAL_SECONDS,
                max_batch_size=MAX_BATCH_SIZE_LARGE,
            )

            dispatcher.emit(self._build_event())
            result = dispatcher.flush(LogWriteReason.MANUAL)

            assert result.failed_count == FAILED_WRITE_COUNT
            assert len(internal_handler.records) == 1
            assert len(runtime_handler.records) == 0
        finally:
            dispatcher.shutdown()
            runtime_logger.handlers.clear()
            internal_logger.handlers.clear()

    def test_log_buffer_dispatcher_shutdown_should_flush_and_stop_worker(self) -> None:
        """
        验证日志缓冲派发器关闭时刷出剩余事件并停止 worker。
        """

        fake_writer = FakeWriter()
        logger = logging.getLogger(LOGGER_SHUTDOWN_NAME)
        dispatcher = LogBufferDispatcher(
            writer=fake_writer,
            logger=logger,
            buffer_max_items=BUFFER_MAX_ITEMS,
            flush_interval_seconds=FLUSH_INTERVAL_SECONDS,
            max_batch_size=MAX_BATCH_SIZE_LARGE,
        )

        dispatcher.emit(self._build_event())
        dispatcher.shutdown()

        assert len(fake_writer.requests) == SHUTDOWN_EXPECTED_REQUEST_COUNT
        assert fake_writer.requests[0].reason == LogWriteReason.SHUTDOWN
        assert dispatcher._worker_stopped is True  # noqa: SLF001
        assert dispatcher._worker_thread is not None  # noqa: SLF001
        assert dispatcher._worker_thread.is_alive() is False  # noqa: SLF001

    def _build_event(self) -> LogEventEnvelope:
        """
        构建测试日志事件。
        """

        return LogEventEnvelope(
            header=LogEventHeader(
                event_id=EVENT_ID,
                occurred_at=datetime.now(UTC),
                level=LogLevel.INFO,
                kind=LogEventKind.ACCESS,
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
                client_ip=CLIENT_IP,
                user_agent=USER_AGENT,
                route_name=ROUTE_NAME,
            ),
        )
