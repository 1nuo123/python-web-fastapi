"""
本地任务分发器基础设施模块。
"""

from __future__ import annotations

from collections.abc import Callable
from http import HTTPStatus
from time import time
from uuid import uuid4

from src.core.exception_contract.error_code_catalog_contract import CoreErrorCode
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.task_contract.message_bus_contract import (
    MessageBus,
    MessagePublishResult,
    TaskMessageEnvelope,
)
from src.core.task_contract.task_dispatcher_contract import (
    TaskDispatcher,
    TaskDispatchResultPayload,
    TaskFailureStage,
)
from src.core.task_contract.task_execution_record_contract import (
    TASK_EXECUTION_STAGE_DISPATCH,
    TASK_EXECUTION_STAGE_LOCAL,
    TaskExecutionStage,
    TaskExecutionStatus,
)
from src.core.task_contract.task_registration_contract import TaskRegistrationEnvelope
from src.core.task_contract.task_runtime_contract import TaskBackend
from src.infrastructure.persistence.orm_model.task_execution_record_orm_model import (
    TaskExecutionRecordOrmModel,
)
from src.infrastructure.task.failed_task_recorder import (
    FailedTaskRecorder,
    TaskFailureRecord,
)
from src.infrastructure.task.task_execution_store import TaskExecutionStore
from src.infrastructure.task.task_registration_registry import TaskRegistrationRegistry
from src.infrastructure.task.task_worker_supervisor import TaskWorkerSupervisor

LOCAL_TASK_RETRY_DELAY_SECONDS = 1
LOCAL_TASK_RETRY_BACKOFF_MULTIPLIER = 2
LOCAL_TASK_RETRY_MAX_DELAY_SECONDS = 30
DEFAULT_TASK_EXECUTION_ATTEMPT_COUNT = 0
LOCAL_TASK_PUBLISH_FAILED_MESSAGE = "本地任务发布失败。"


class LocalTaskDispatcher(TaskDispatcher):
    """
    本地任务分发器。
    """

    def __init__(
        self,
        *,
        message_bus: MessageBus,
        registration_registry: TaskRegistrationRegistry | None = None,
        worker_supervisor: TaskWorkerSupervisor | None = None,
        failed_task_recorder: FailedTaskRecorder,
        task_execution_store: TaskExecutionStore,
        worker_enabled: bool,
        inline_execute_enabled: bool,
        retry_delay_seconds: int = LOCAL_TASK_RETRY_DELAY_SECONDS,
        retry_backoff_multiplier: int = LOCAL_TASK_RETRY_BACKOFF_MULTIPLIER,
        retry_max_delay_seconds: int = LOCAL_TASK_RETRY_MAX_DELAY_SECONDS,
        failure_callback: Callable[[TaskFailureRecord], None] | None = None,
    ) -> None:
        """
        初始化本地任务分发器。
        """

        self._message_bus = message_bus
        self._registration_registry = self._resolve_registration_registry(
            registration_registry=registration_registry,
            worker_supervisor=worker_supervisor,
        )
        self._failed_task_recorder = failed_task_recorder
        self._task_execution_store = task_execution_store
        self._worker_enabled = worker_enabled
        self._inline_execute_enabled = inline_execute_enabled
        self._retry_delay_seconds = retry_delay_seconds
        self._retry_backoff_multiplier = retry_backoff_multiplier
        self._retry_max_delay_seconds = retry_max_delay_seconds
        self._failure_callback = failure_callback

    def dispatch(self, message: TaskMessageEnvelope) -> TaskDispatchResultPayload:
        """
        分发当前任务消息。
        """

        registration = self._registration_registry.get_enabled_registration_for_backend(
            message.payload.job_kind,
            backend=TaskBackend.LOCAL,
        )
        queue_name = self._resolve_queue_name(registration)
        store_result = self._task_execution_store.reserve_with_outbox(
            record=self._build_execution_record(message=message, queue_name=queue_name),
            message=message,
            backend=TaskBackend.LOCAL,
            queue_name=queue_name,
        )
        if store_result.created is False:
            return TaskDispatchResultPayload(
                task_id=store_result.record.task_id,
                job_kind=store_result.record.job_kind,
                dispatched=False,
                retry_limit=message.payload.retry_limit,
                backend=TaskBackend.LOCAL,
                queue_name=queue_name,
                published=False,
                worker_enabled=self._worker_enabled,
                inline_execute_enabled=self._inline_execute_enabled,
                execution_status=TaskExecutionStatus(store_result.record.status),
                execution_stage=TaskExecutionStage(
                    store_result.record.stage or TaskExecutionStage.DISPATCH.value
                ),
                reused_existing_record=True,
            )
        if self._inline_execute_enabled:
            try:
                executed_record = self._execute_handler(
                    message=message,
                    queue_name=queue_name,
                )
                publish_result = self._message_bus.publish(message)
                self._raise_when_publish_failed(publish_result)
                self._task_execution_store.mark_outbox_published(
                    message_id=message.header.message_id
                )
            except Exception as exc:
                self._task_execution_store.mark_outbox_failed(
                    message_id=message.header.message_id,
                    failure_reason=str(exc),
                )
                raise
            execution_status = TaskExecutionStatus(executed_record.status)
            execution_stage = TaskExecutionStage(
                executed_record.stage or TASK_EXECUTION_STAGE_LOCAL
            )
        else:
            try:
                publish_result = self._message_bus.publish(message)
                self._raise_when_publish_failed(publish_result)
            except Exception as exc:
                self._task_execution_store.mark_failed(
                    job_kind=message.payload.job_kind,
                    deduplication_key=message.payload.deduplication_key,
                    attempt_count=DEFAULT_TASK_EXECUTION_ATTEMPT_COUNT,
                    failed_at_epoch=int(time()),
                    last_error_type=type(exc).__name__,
                    last_error_message=str(exc),
                    backend=TaskBackend.LOCAL,
                    queue_name=queue_name,
                    stage=TaskExecutionStage.DISPATCH,
                    message_id=message.header.message_id,
                )
                if isinstance(exc, HttpFaultException):
                    raise
                raise HttpFaultException(
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                    error_code=CoreErrorCode.TASK_FAILED,
                    message=LOCAL_TASK_PUBLISH_FAILED_MESSAGE,
                    detail=str(exc),
                ) from exc
            published_record = self._task_execution_store.mark_published(
                job_kind=message.payload.job_kind,
                deduplication_key=message.payload.deduplication_key,
                attempt_count=DEFAULT_TASK_EXECUTION_ATTEMPT_COUNT,
                backend=TaskBackend.LOCAL,
                queue_name=queue_name,
                message_id=message.header.message_id,
            )
            execution_status = TaskExecutionStatus(published_record.status)
            execution_stage = TaskExecutionStage(
                published_record.stage or TASK_EXECUTION_STAGE_DISPATCH
            )
        return TaskDispatchResultPayload(
            task_id=message.header.message_id,
            job_kind=message.payload.job_kind,
            dispatched=True,
            retry_limit=message.payload.retry_limit,
            backend=TaskBackend.LOCAL,
            queue_name=queue_name,
            published=publish_result.published,
            worker_enabled=self._worker_enabled,
            inline_execute_enabled=self._inline_execute_enabled,
            execution_status=execution_status,
            execution_stage=execution_stage,
            reused_existing_record=False,
        )

    def shutdown(self) -> None:
        """
        关闭当前资源或组件。
        """

        return None

    def _raise_when_publish_failed(self, publish_result: MessagePublishResult) -> None:
        """在消息总线拒绝发布时抛出容量异常。

        :param publish_result: 消息发布结果。
        :type publish_result: MessagePublishResult
        :returns: 无返回值。
        :rtype: None
        :raises HttpFaultException: 当消息未发布时抛出。
        """

        if publish_result.published:
            return
        raise HttpFaultException(
            status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            error_code=CoreErrorCode.CAPACITY_EXHAUSTED,
            message=LOCAL_TASK_PUBLISH_FAILED_MESSAGE,
            detail=publish_result.failure_reason,
        )

    def _execute_handler(
        self,
        *,
        message: TaskMessageEnvelope,
        queue_name: str,
    ) -> TaskExecutionRecordOrmModel:
        """
        执行本地处理器。
        """

        invocation = self._registration_registry.validate_message_payload(message)
        handler = invocation.binding.handler
        current_attempt = 0
        last_error: Exception | None = None
        while current_attempt <= message.payload.retry_limit:
            try:
                self._task_execution_store.mark_running(
                    job_kind=message.payload.job_kind,
                    deduplication_key=message.payload.deduplication_key,
                    attempt_count=current_attempt,
                    backend=TaskBackend.LOCAL,
                    queue_name=queue_name,
                    stage=TaskExecutionStage.LOCAL_EXECUTION,
                )
                handler.handle(invocation)
                return self._task_execution_store.mark_success(
                    job_kind=message.payload.job_kind,
                    deduplication_key=message.payload.deduplication_key,
                    attempt_count=current_attempt + 1,
                    backend=TaskBackend.LOCAL,
                    queue_name=queue_name,
                    stage=TaskExecutionStage.LOCAL_EXECUTION,
                )
            except Exception as exc:
                last_error = exc
                current_attempt += 1
                if current_attempt <= message.payload.retry_limit:
                    next_retry_at_epoch = int(time()) + self._resolve_retry_delay(
                        attempt_count=current_attempt,
                        retry_limit=message.payload.retry_limit,
                    )
                    self._task_execution_store.mark_retrying(
                        job_kind=message.payload.job_kind,
                        deduplication_key=message.payload.deduplication_key,
                        attempt_count=current_attempt,
                        next_retry_at_epoch=next_retry_at_epoch,
                        last_error_type=type(exc).__name__,
                        last_error_message=str(exc),
                        backend=TaskBackend.LOCAL,
                        queue_name=queue_name,
                        stage=TaskExecutionStage.LOCAL_EXECUTION,
                    )
                    continue
        record = TaskFailureRecord(
            task_id=message.header.message_id,
            job_kind=message.payload.job_kind,
            message="任务执行失败。",
            retry_count=current_attempt,
            backend=TaskBackend.LOCAL,
            stage=TaskFailureStage.LOCAL_EXECUTION,
            last_error=str(last_error),
            queue_name=queue_name,
            payload_kind=message.payload.payload_kind,
            request_id=message.header.request_id,
            trace_id=message.header.trace_id,
            deduplication_key=message.payload.deduplication_key,
            attempt_count=current_attempt,
        )
        self._task_execution_store.mark_failed(
            job_kind=message.payload.job_kind,
            deduplication_key=message.payload.deduplication_key,
            attempt_count=current_attempt,
            failed_at_epoch=int(time()),
            last_error_type=type(last_error).__name__ if last_error is not None else "Exception",
            last_error_message=str(last_error),
            backend=TaskBackend.LOCAL,
            queue_name=queue_name,
            stage=TaskExecutionStage.LOCAL_EXECUTION,
        )
        self._failed_task_recorder.record(record)
        raise HttpFaultException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            error_code=CoreErrorCode.TASK_FAILED,
            message="任务执行失败。",
            detail=str(last_error),
        ) from last_error

    def _resolve_retry_delay(self, *, attempt_count: int, retry_limit: int) -> int:
        """
        解析本地任务重试延迟。
        """

        if attempt_count <= 0:
            return 0
        delay_seconds = int(
            self._retry_delay_seconds * (self._retry_backoff_multiplier ** (attempt_count - 1))
        )
        if self._retry_max_delay_seconds <= 0:
            return min(delay_seconds, retry_limit + 1)
        return min(delay_seconds, self._retry_max_delay_seconds)

    def _build_execution_record(
        self,
        *,
        message: TaskMessageEnvelope,
        queue_name: str,
    ) -> TaskExecutionRecordOrmModel:
        """
        构建执行记录。
        """

        return TaskExecutionRecordOrmModel(
            record_id=str(uuid4()),
            task_id=message.header.message_id,
            job_kind=message.payload.job_kind,
            deduplication_key=message.payload.deduplication_key,
            request_id=message.header.request_id,
            trace_id=message.header.trace_id,
            created_at_epoch=message.header.created_at_epoch,
            backend=TaskBackend.LOCAL.value,
            status=TaskExecutionStatus.RESERVED.value,
            stage=TaskExecutionStage.DISPATCH.value,
            attempt_count=DEFAULT_TASK_EXECUTION_ATTEMPT_COUNT,
            queue_name=queue_name,
            payload_kind=message.payload.payload_kind,
            payload_json=message.payload.payload_json,
        )

    def _resolve_queue_name(self, registration: TaskRegistrationEnvelope) -> str:
        """
        解析当前任务对应的队列名。
        """

        return registration.header.job_kind

    def _resolve_registration_registry(
        self,
        *,
        registration_registry: TaskRegistrationRegistry | None,
        worker_supervisor: TaskWorkerSupervisor | None,
    ) -> TaskRegistrationRegistry:
        """
        解析任务注册中心。
        """

        if registration_registry is not None:
            return registration_registry
        if worker_supervisor is None:
            raise TypeError("必须提供 registration_registry 或 worker_supervisor。")
        raise TypeError("硬迁移后必须显式提供 registration_registry。")
