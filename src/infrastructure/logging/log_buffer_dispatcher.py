"""
日志缓冲派发器模块。
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from queue import Queue

from src.core.logging_contract.log_event_contract import LogEventEnvelope
from src.core.logging_contract.log_writer_contract import (
    LogWriteReason,
    LogWriteRequest,
    LogWriteResult,
)
from src.infrastructure.logging.database_log_writer import DatabaseLogWriter

LOG_BUFFER_INTERNAL_LOGGER_NAME = "fastapi_web_skeleton.log_buffer.internal"
LOG_BUFFER_WORKER_THREAD_NAME = "log-buffer-dispatcher-worker"
LOG_BUFFER_MINIMUM_CAPACITY = 1
EMPTY_WRITE_RESULT = LogWriteResult(
    written_count=0,
    failed_count=0,
    degraded_to_stdout=False,
    failure_reason=None,
)


@dataclass(frozen=True, slots=True)
class LogBufferWorkerStopSignal:
    """
    日志缓冲后台 worker 停止信号。
    """


LOG_BUFFER_WORKER_STOP_SIGNAL = LogBufferWorkerStopSignal()
LogBufferWorkerItem = LogWriteRequest | LogBufferWorkerStopSignal


@dataclass(slots=True)
class LogBufferDispatcher:
    """
    日志缓冲派发器。
    """

    writer: DatabaseLogWriter
    logger: logging.Logger
    buffer_max_items: int
    flush_interval_seconds: int
    max_batch_size: int
    internal_logger: logging.Logger | None = None
    _events: list[LogEventEnvelope] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _last_flush_epoch: float = field(default_factory=time.time)
    _write_queue: Queue[LogBufferWorkerItem] = field(init=False)
    _worker_stopped: bool = False
    _worker_thread: threading.Thread | None = None

    def __post_init__(self) -> None:
        """
        初始化独立内部错误 logger 和后台写入 worker。

        :returns: 无返回值。
        :rtype: None
        """

        if self.buffer_max_items < LOG_BUFFER_MINIMUM_CAPACITY:
            raise ValueError("日志缓冲容量必须大于 0。")
        self._write_queue = Queue(maxsize=self.buffer_max_items)
        if self.internal_logger is None:
            logger = logging.getLogger(LOG_BUFFER_INTERNAL_LOGGER_NAME)
            logger.propagate = False
            if len(logger.handlers) == 0:
                logger.addHandler(logging.NullHandler())
            self.internal_logger = logger
        self._start_worker()

    def emit(self, event: LogEventEnvelope) -> None:
        """
        接收日志事件并在必要时触发刷盘。

        :param event: 日志事件信封。
        :type event: LogEventEnvelope
        :returns: 无返回值。
        :rtype: None
        """

        write_requests: list[LogWriteRequest] = []
        with self._lock:
            if len(self._events) >= self.buffer_max_items:
                request = self._drain_events_locked(LogWriteReason.BUFFER_LIMIT)
                if request is not None:
                    write_requests.append(request)
            self._events.append(event)
            if self._should_flush_interval_locked():
                request = self._drain_events_locked(LogWriteReason.INTERVAL)
                if request is not None:
                    write_requests.append(request)
            elif len(self._events) >= self.max_batch_size:
                request = self._drain_events_locked(LogWriteReason.BUFFER_LIMIT)
                if request is not None:
                    write_requests.append(request)
        for request in write_requests:
            self._enqueue_write_request(request)

    def flush(self, reason: LogWriteReason) -> LogWriteResult:
        """
        显式刷新缓冲区。

        :param reason: 刷盘触发原因。
        :type reason: LogWriteReason
        :returns: 日志写入结果。
        :rtype: LogWriteResult
        """

        with self._lock:
            request = self._drain_events_locked(reason)
        self._write_queue.join()
        if request is None:
            return EMPTY_WRITE_RESULT
        return self._write_batch(request)

    def shutdown(self) -> None:
        """
        停止后台 worker 并刷出剩余日志。

        :returns: 无返回值。
        :rtype: None
        """

        if self._worker_stopped:
            return
        self.flush(LogWriteReason.SHUTDOWN)
        self._worker_stopped = True
        self._write_queue.put(LOG_BUFFER_WORKER_STOP_SIGNAL)
        if self._worker_thread is not None:
            self._worker_thread.join()

    def _should_flush_interval_locked(self) -> bool:
        """
        在持锁状态下判断是否到达时间窗口。

        :returns: 是否应当按时间窗口刷盘。
        :rtype: bool
        """

        return (time.time() - self._last_flush_epoch) >= self.flush_interval_seconds

    def _drain_events_locked(self, reason: LogWriteReason) -> LogWriteRequest | None:
        """
        在持锁状态下交换缓冲区。

        :param reason: 刷盘触发原因。
        :type reason: LogWriteReason
        :returns: 待写入请求；无待刷事件时返回空。
        :rtype: LogWriteRequest | None
        """

        if not self._events:
            return None
        write_events = list(self._events)
        self._events.clear()
        self._last_flush_epoch = time.time()
        return LogWriteRequest(
            reason=reason,
            events=write_events,
        )

    def _start_worker(self) -> None:
        """
        启动后台写入 worker。

        :returns: 无返回值。
        :rtype: None
        """

        self._worker_thread = threading.Thread(
            target=self._run_worker,
            name=LOG_BUFFER_WORKER_THREAD_NAME,
            daemon=True,
        )
        self._worker_thread.start()

    def _run_worker(self) -> None:
        """
        后台消费日志写入请求。

        :returns: 无返回值。
        :rtype: None
        """

        while True:
            item = self._write_queue.get()
            try:
                if isinstance(item, LogBufferWorkerStopSignal):
                    return
                self._write_batch(item)
            finally:
                self._write_queue.task_done()

    def _enqueue_write_request(self, request: LogWriteRequest) -> None:
        """
        将写入请求交给后台 worker。

        :param request: 日志写入请求。
        :type request: LogWriteRequest
        :returns: 无返回值。
        :rtype: None
        """

        if self._worker_stopped:
            self._write_batch(request)
            return
        self._write_queue.put(request)

    def _write_batch(self, request: LogWriteRequest) -> LogWriteResult:
        """
        在锁外写入日志批次。

        :param request: 日志写入请求。
        :type request: LogWriteRequest
        :returns: 日志写入结果。
        :rtype: LogWriteResult
        """

        result = self.writer.write_batch(request)
        if result.failed_count > 0:
            internal_logger = self.internal_logger
            if internal_logger is None:
                raise RuntimeError("日志缓冲内部 logger 尚未初始化。")
            internal_logger.error(
                "日志批量刷盘失败：written=%s failed=%s reason=%s",
                result.written_count,
                result.failed_count,
                result.failure_reason,
            )
        return result
