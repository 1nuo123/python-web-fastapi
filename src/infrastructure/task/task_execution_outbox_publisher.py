"""
任务执行 Outbox 发布器模块。
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from time import time
from typing import TYPE_CHECKING

from src.core.task_contract.message_bus_contract import MessageBus, TaskMessageEnvelope
from src.core.task_contract.task_runtime_contract import TaskBackend
from src.infrastructure.task.task_execution_store import (
    DEFAULT_TASK_EXECUTION_ATTEMPT_COUNT,
    TaskExecutionStore,
)

if TYPE_CHECKING:
    from src.infrastructure.task.funboost_task_bootstrapper import FunboostTaskBootstrapper

TASK_EXECUTION_OUTBOX_DEFAULT_LIMIT = 100
TASK_EXECUTION_OUTBOX_BACKGROUND_INTERVAL_SECONDS = 5.0
TASK_EXECUTION_OUTBOX_BACKGROUND_STALE_SECONDS = 60
FUNBOOST_OUTBOX_BOOTSTRAPPER_MISSING_MESSAGE = "Funboost Outbox 发布器未装配。"
TASK_EXECUTION_OUTBOX_FAILURE_REASON_MAX_LENGTH = 512
TASK_EXECUTION_OUTBOX_WORKER_THREAD_NAME = "task-execution-outbox-publisher"
TASK_EXECUTION_OUTBOX_RESCAN_FAILURE_MESSAGE = "任务 Outbox 后台重扫失败。"
LOCAL_OUTBOX_PUBLISH_REJECTED_MESSAGE = "本地消息总线拒绝发布 Outbox 消息。"


class TaskExecutionOutboxPublishError(RuntimeError):
    """
    任务执行 Outbox 发布错误。
    """


@dataclass(frozen=True, slots=True)
class TaskExecutionOutboxPublishResult:
    """
    任务执行 Outbox 发布结果。
    """

    scanned_count: int
    published_count: int
    failed_count: int


class TaskExecutionOutboxPublisher:
    """
    任务执行 Outbox 重扫发布器。
    """

    def __init__(
        self,
        *,
        task_execution_store: TaskExecutionStore,
        local_message_bus: MessageBus,
        logger: logging.Logger,
        funboost_bootstrapper: FunboostTaskBootstrapper | None = None,
        background_enabled: bool = False,
        background_interval_seconds: float = (TASK_EXECUTION_OUTBOX_BACKGROUND_INTERVAL_SECONDS),
        background_stale_seconds: int = TASK_EXECUTION_OUTBOX_BACKGROUND_STALE_SECONDS,
        background_limit: int = TASK_EXECUTION_OUTBOX_DEFAULT_LIMIT,
    ) -> None:
        """
        初始化任务执行 Outbox 发布器。
        """

        self._task_execution_store = task_execution_store
        self._local_message_bus = local_message_bus
        self._logger = logger
        self._funboost_bootstrapper = funboost_bootstrapper
        self._background_interval_seconds = background_interval_seconds
        self._background_stale_seconds = background_stale_seconds
        self._background_limit = background_limit
        self._publish_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._worker_thread: threading.Thread | None = None
        if background_enabled:
            self.start_background_worker()

    def publish_reserved(
        self,
        *,
        limit: int = TASK_EXECUTION_OUTBOX_DEFAULT_LIMIT,
        created_before_epoch: int | None = None,
    ) -> TaskExecutionOutboxPublishResult:
        """
        重扫并发布待发布 Outbox 消息。
        """

        with self._publish_lock:
            reserved_records = self._task_execution_store.list_reserved_outbox(
                limit=limit,
                created_before_epoch=created_before_epoch,
            )
            published_count = 0
            failed_count = 0
            for outbox_record in reserved_records:
                message_published = False
                try:
                    message = TaskMessageEnvelope.model_validate_json(outbox_record.message_json)
                    self._publish_message(
                        backend=TaskBackend(outbox_record.backend),
                        message=message,
                    )
                    message_published = True
                    self._task_execution_store.mark_published(
                        job_kind=outbox_record.job_kind,
                        deduplication_key=outbox_record.deduplication_key,
                        attempt_count=DEFAULT_TASK_EXECUTION_ATTEMPT_COUNT,
                        backend=TaskBackend(outbox_record.backend),
                        queue_name=outbox_record.queue_name,
                        message_id=outbox_record.message_id,
                    )
                    published_count += 1
                except Exception as exc:
                    if message_published:
                        failed_count += 1
                        continue
                    self._task_execution_store.mark_outbox_failed(
                        message_id=outbox_record.message_id,
                        failure_reason=str(exc)[:TASK_EXECUTION_OUTBOX_FAILURE_REASON_MAX_LENGTH],
                    )
                    failed_count += 1
        return TaskExecutionOutboxPublishResult(
            scanned_count=len(reserved_records),
            published_count=published_count,
            failed_count=failed_count,
        )

    def start_background_worker(self) -> None:
        """
        启动后台 Outbox 重扫 worker。

        :returns: 无返回值。
        :rtype: None
        """

        if self._worker_thread is not None:
            return
        self._worker_thread = threading.Thread(
            target=self._run_background_worker,
            name=TASK_EXECUTION_OUTBOX_WORKER_THREAD_NAME,
            daemon=True,
        )
        self._worker_thread.start()

    def shutdown(self) -> None:
        """
        停止后台 Outbox 重扫 worker。

        :returns: 无返回值。
        :rtype: None
        """

        self._stop_event.set()
        if self._worker_thread is not None:
            self._worker_thread.join()
            self._worker_thread = None

    def _run_background_worker(self) -> None:
        """
        周期性重扫已过安全窗口的 RESERVED Outbox。

        :returns: 无返回值。
        :rtype: None
        """

        while not self._stop_event.wait(self._background_interval_seconds):
            stale_before_epoch = int(time()) - self._background_stale_seconds
            try:
                self.publish_reserved(
                    limit=self._background_limit,
                    created_before_epoch=stale_before_epoch,
                )
            except Exception:
                self._logger.exception(TASK_EXECUTION_OUTBOX_RESCAN_FAILURE_MESSAGE)

    def _publish_message(
        self,
        *,
        backend: TaskBackend,
        message: TaskMessageEnvelope,
    ) -> None:
        """
        按后端发布 Outbox 消息。
        """

        if backend == TaskBackend.LOCAL:
            result = self._local_message_bus.publish(message)
            if not result.published:
                raise TaskExecutionOutboxPublishError(
                    result.failure_reason or LOCAL_OUTBOX_PUBLISH_REJECTED_MESSAGE
                )
            return
        if self._funboost_bootstrapper is None:
            raise TaskExecutionOutboxPublishError(FUNBOOST_OUTBOX_BOOTSTRAPPER_MISSING_MESSAGE)
        self._funboost_bootstrapper.publish(message)
