"""
任务执行 Outbox 发布器模块。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from time import time
from typing import TYPE_CHECKING
from uuid import uuid4

from src.core.outbox_contract.reliable_outbox_contract import (
    OutboxDeliveryOutcome,
    ReliableOutboxAdapterPort,
)
from src.core.task_contract.message_bus_contract import MessageBus, TaskMessageEnvelope
from src.core.task_contract.task_runtime_contract import TaskBackend
from src.infrastructure.outbox.reliable_outbox_runner import ReliableOutboxRunner
from src.infrastructure.persistence.orm_model.task_execution_outbox_orm_model import (
    TaskExecutionOutboxOrmModel,
)
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
TASK_EXECUTION_OUTBOX_MAX_ATTEMPTS = 5
TASK_EXECUTION_OUTBOX_RETRY_DELAY_SECONDS = 1
TASK_EXECUTION_OUTBOX_RETRY_BACKOFF_MULTIPLIER = 2
TASK_EXECUTION_OUTBOX_RETRY_MAX_DELAY_SECONDS = 60


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
    retrying_count: int = 0
    unknown_count: int = 0


class TaskExecutionOutboxAdapter(ReliableOutboxAdapterPort[TaskExecutionOutboxOrmModel]):
    """把现有 task RESERVED/PUBLISHED 语义映射到通用 runner。"""

    def __init__(
        self,
        *,
        task_execution_store: TaskExecutionStore,
        local_message_bus: MessageBus,
        funboost_bootstrapper: FunboostTaskBootstrapper | None,
        max_attempts: int = TASK_EXECUTION_OUTBOX_MAX_ATTEMPTS,
        retry_delay_seconds: int = TASK_EXECUTION_OUTBOX_RETRY_DELAY_SECONDS,
        retry_backoff_multiplier: int = TASK_EXECUTION_OUTBOX_RETRY_BACKOFF_MULTIPLIER,
        retry_max_delay_seconds: int = TASK_EXECUTION_OUTBOX_RETRY_MAX_DELAY_SECONDS,
    ) -> None:
        self._task_execution_store = task_execution_store
        self._local_message_bus = local_message_bus
        self._funboost_bootstrapper = funboost_bootstrapper
        self._max_attempts = max_attempts
        self._retry_delay_seconds = retry_delay_seconds
        self._retry_backoff_multiplier = retry_backoff_multiplier
        self._retry_max_delay_seconds = retry_max_delay_seconds
        self._claim_owner = uuid4().hex

    def claim(
        self,
        *,
        limit: int,
        stale_before_epoch: int | None,
    ) -> list[TaskExecutionOutboxOrmModel]:
        return self._task_execution_store.list_reserved_outbox(
            limit=limit,
            created_before_epoch=stale_before_epoch,
            claim_owner=self._claim_owner,
        )

    def deliver(self, record: TaskExecutionOutboxOrmModel) -> OutboxDeliveryOutcome:
        attempt_count = record.attempt_count + 1
        try:
            message = TaskMessageEnvelope.model_validate_json(record.message_json)
            backend = TaskBackend(record.backend)
        except (TypeError, ValueError) as exc:
            self._task_execution_store.mark_outbox_failed_permanent(
                message_id=record.message_id,
                attempt_count=attempt_count,
                error_type=type(exc).__name__,
                error_message=str(exc)[:TASK_EXECUTION_OUTBOX_FAILURE_REASON_MAX_LENGTH],
            )
            return OutboxDeliveryOutcome.FAILED_PERMANENT
        try:
            self._publish_message(backend=backend, message=message)
        except Exception as exc:
            reason = str(exc)[:TASK_EXECUTION_OUTBOX_FAILURE_REASON_MAX_LENGTH]
            if self._is_permanent_publish_error(exc):
                self._task_execution_store.mark_outbox_failed_permanent(
                    message_id=record.message_id,
                    attempt_count=attempt_count,
                    error_type=type(exc).__name__,
                    error_message=reason,
                )
                return OutboxDeliveryOutcome.FAILED_PERMANENT
            permanently_failed = self._record_retry_or_permanent(
                record=record,
                attempt_count=attempt_count,
                error_type=type(exc).__name__,
                error_message=reason,
            )
            return (
                OutboxDeliveryOutcome.FAILED_PERMANENT
                if permanently_failed
                else OutboxDeliveryOutcome.DEFERRED
            )
        try:
            self._task_execution_store.mark_published(
                job_kind=record.job_kind,
                deduplication_key=record.deduplication_key,
                attempt_count=DEFAULT_TASK_EXECUTION_ATTEMPT_COUNT,
                backend=TaskBackend(record.backend),
                queue_name=record.queue_name,
                message_id=record.message_id,
                outbox_attempt_count=attempt_count,
            )
        except Exception as exc:
            self._task_execution_store.mark_outbox_unknown(
                message_id=record.message_id,
                attempt_count=attempt_count,
                error_type=type(exc).__name__,
                error_message=str(exc)[:TASK_EXECUTION_OUTBOX_FAILURE_REASON_MAX_LENGTH],
            )
            return OutboxDeliveryOutcome.UNKNOWN
        return OutboxDeliveryOutcome.DELIVERED

    def record_failure(
        self,
        record: TaskExecutionOutboxOrmModel,
        failure_reason: str,
    ) -> None:
        attempt_count = record.attempt_count + 1
        self._record_retry_or_permanent(
            record=record,
            attempt_count=attempt_count,
            error_type="OutboxRunnerError",
            error_message=failure_reason[:TASK_EXECUTION_OUTBOX_FAILURE_REASON_MAX_LENGTH],
        )

    def _record_retry_or_permanent(
        self,
        *,
        record: TaskExecutionOutboxOrmModel,
        attempt_count: int,
        error_type: str,
        error_message: str,
    ) -> bool:
        if attempt_count >= self._max_attempts:
            self._task_execution_store.mark_outbox_failed_permanent(
                message_id=record.message_id,
                attempt_count=attempt_count,
                error_type=error_type,
                error_message=error_message,
            )
            return True
        delay = min(
            self._retry_delay_seconds * self._retry_backoff_multiplier ** max(attempt_count - 1, 0),
            self._retry_max_delay_seconds,
        )
        self._task_execution_store.mark_outbox_retrying(
            message_id=record.message_id,
            attempt_count=attempt_count,
            next_retry_at_epoch=int(time()) + delay,
            last_error_type=error_type,
            last_error_message=error_message,
        )
        return False

    def _is_permanent_publish_error(self, error: Exception) -> bool:
        return isinstance(error, TaskExecutionOutboxPublishError) and str(error) == (
            FUNBOOST_OUTBOX_BOOTSTRAPPER_MISSING_MESSAGE
        )

    def _publish_message(
        self,
        *,
        backend: TaskBackend,
        message: TaskMessageEnvelope,
    ) -> None:
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

        self._logger = logger
        self._runner = ReliableOutboxRunner(
            adapter=TaskExecutionOutboxAdapter(
                task_execution_store=task_execution_store,
                local_message_bus=local_message_bus,
                funboost_bootstrapper=funboost_bootstrapper,
            ),
            logger=logger,
            worker_name=TASK_EXECUTION_OUTBOX_WORKER_THREAD_NAME,
            interval_seconds=background_interval_seconds,
            stale_seconds=background_stale_seconds,
            batch_limit=background_limit,
        )
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

        result = self._runner.run_once(
            limit=limit,
            stale_before_epoch=created_before_epoch,
        )
        return TaskExecutionOutboxPublishResult(
            scanned_count=result.scanned_count,
            published_count=result.delivered_count,
            failed_count=result.failed_count + result.permanently_failed_count,
            retrying_count=result.deferred_count,
            unknown_count=result.unknown_count,
        )

    def start_background_worker(self) -> None:
        """
        启动后台 Outbox 重扫 worker。

        :returns: 无返回值。
        :rtype: None
        """

        self._runner.start()

    def shutdown(self) -> None:
        """
        停止后台 Outbox 重扫 worker。

        :returns: 无返回值。
        :rtype: None
        """

        self._runner.shutdown()
