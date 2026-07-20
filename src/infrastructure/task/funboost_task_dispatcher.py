"""
Funboost 任务分发器基础设施模块。
"""

from __future__ import annotations

from collections.abc import Callable
from http import HTTPStatus
from time import time
from uuid import uuid4

from src.core.exception_contract.error_code_catalog_contract import CoreErrorCode
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.task_contract.message_bus_contract import TaskMessageEnvelope
from src.core.task_contract.task_dispatcher_contract import (
    TaskDispatcher,
    TaskDispatchResultPayload,
    TaskFailureStage,
)
from src.core.task_contract.task_execution_record_contract import (
    TaskExecutionStage,
    TaskExecutionStatus,
)
from src.core.task_contract.task_registration_contract import (
    FunboostTaskRegistrationDetail,
)
from src.core.task_contract.task_runtime_contract import TaskBackend
from src.infrastructure.persistence.orm_model.task_execution_record_orm_model import (
    TaskExecutionRecordOrmModel,
)
from src.infrastructure.task.failed_task_recorder import (
    FailedTaskRecorder,
    TaskFailureRecord,
)
from src.infrastructure.task.funboost_task_bootstrapper import FunboostTaskBootstrapper
from src.infrastructure.task.task_execution_store import TaskExecutionStore
from src.infrastructure.task.task_registration_registry import TaskRegistrationRegistry

DEFAULT_TASK_EXECUTION_ATTEMPT_COUNT = 0


class FunboostTaskDispatcher(TaskDispatcher):
    """
    Funboost 任务分发器。
    """

    def __init__(
        self,
        *,
        registration_registry: TaskRegistrationRegistry,
        bootstrapper: FunboostTaskBootstrapper,
        failed_task_recorder: FailedTaskRecorder,
        task_execution_store: TaskExecutionStore,
        worker_enabled: bool,
        failure_callback: Callable[[TaskFailureRecord], None] | None = None,
    ) -> None:
        """
        初始化 Funboost 任务分发器。
        """

        self._registration_registry = registration_registry
        self._bootstrapper = bootstrapper
        self._failed_task_recorder = failed_task_recorder
        self._task_execution_store = task_execution_store
        self._worker_enabled = worker_enabled
        self._failure_callback = failure_callback

    def dispatch(self, message: TaskMessageEnvelope) -> TaskDispatchResultPayload:
        """
        分发当前任务消息。
        """

        registration = self._registration_registry.get_enabled_registration_for_backend(
            message.payload.job_kind,
            backend=TaskBackend.FUNBOOST,
        )
        if not isinstance(registration.detail, FunboostTaskRegistrationDetail):
            raise HttpFaultException(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                error_code=CoreErrorCode.CONFIG_INVALID,
                message=f"任务 `{message.payload.job_kind}` 不是 Funboost 任务注册项。",
            )
        reserve_result = self._task_execution_store.reserve_with_outbox(
            record=self._build_execution_record(
                message=message,
                queue_name=registration.detail.queue_name,
            ),
            message=message,
            backend=TaskBackend.FUNBOOST,
            queue_name=registration.detail.queue_name,
        )
        if reserve_result.created is False:
            return TaskDispatchResultPayload(
                task_id=reserve_result.record.task_id,
                job_kind=reserve_result.record.job_kind,
                dispatched=False,
                retry_limit=message.payload.retry_limit,
                backend=TaskBackend.FUNBOOST,
                queue_name=registration.detail.queue_name,
                published=False,
                worker_enabled=self._worker_enabled,
                inline_execute_enabled=False,
                execution_status=TaskExecutionStatus(reserve_result.record.status),
                execution_stage=TaskExecutionStage(
                    reserve_result.record.stage or TaskExecutionStage.DISPATCH.value
                ),
                reused_existing_record=True,
            )
        try:
            self._bootstrapper.publish(message)
        except Exception as exc:
            self._task_execution_store.mark_failed(
                job_kind=message.payload.job_kind,
                deduplication_key=message.payload.deduplication_key,
                attempt_count=DEFAULT_TASK_EXECUTION_ATTEMPT_COUNT,
                failed_at_epoch=int(time()),
                last_error_type=type(exc).__name__,
                last_error_message=str(exc),
                backend=TaskBackend.FUNBOOST,
                queue_name=registration.detail.queue_name,
                stage=TaskExecutionStage.DISPATCH,
                message_id=message.header.message_id,
            )
            record = TaskFailureRecord(
                task_id=message.header.message_id,
                job_kind=message.payload.job_kind,
                message="Funboost 任务发布失败。",
                retry_count=DEFAULT_TASK_EXECUTION_ATTEMPT_COUNT,
                backend=TaskBackend.FUNBOOST,
                stage=TaskFailureStage.DISPATCH_PUBLISH,
                last_error=str(exc),
                queue_name=registration.detail.queue_name,
                payload_kind=message.payload.payload_kind,
                request_id=message.header.request_id,
                trace_id=message.header.trace_id,
                deduplication_key=message.payload.deduplication_key,
                attempt_count=DEFAULT_TASK_EXECUTION_ATTEMPT_COUNT,
            )
            self._failed_task_recorder.record(record)
            raise HttpFaultException(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                error_code=CoreErrorCode.TASK_FAILED,
                message="Funboost 任务发布失败。",
                detail=str(exc),
            ) from exc
        published_record = self._task_execution_store.mark_published(
            job_kind=message.payload.job_kind,
            deduplication_key=message.payload.deduplication_key,
            attempt_count=DEFAULT_TASK_EXECUTION_ATTEMPT_COUNT,
            backend=TaskBackend.FUNBOOST,
            queue_name=registration.detail.queue_name,
            message_id=message.header.message_id,
        )
        return TaskDispatchResultPayload(
            task_id=message.header.message_id,
            job_kind=message.payload.job_kind,
            dispatched=True,
            retry_limit=message.payload.retry_limit,
            backend=TaskBackend.FUNBOOST,
            queue_name=registration.detail.queue_name,
            published=True,
            worker_enabled=self._worker_enabled,
            inline_execute_enabled=False,
            execution_status=TaskExecutionStatus(published_record.status),
            execution_stage=TaskExecutionStage.DISPATCH,
            reused_existing_record=False,
        )

    def shutdown(self) -> None:
        """
        关闭当前分发器。
        """

        self._bootstrapper.shutdown()

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
            backend=TaskBackend.FUNBOOST.value,
            status=TaskExecutionStatus.RESERVED.value,
            stage=TaskExecutionStage.DISPATCH.value,
            attempt_count=DEFAULT_TASK_EXECUTION_ATTEMPT_COUNT,
            queue_name=queue_name,
            payload_kind=message.payload.payload_kind,
            payload_json=message.payload.payload_json,
        )
