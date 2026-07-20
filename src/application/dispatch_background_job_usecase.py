"""
分发后台任务用例应用层模块。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

from pydantic import BaseModel

from src.application.ports.task_runtime_port import TaskRuntimePort
from src.core.task_contract.message_bus_contract import (
    TaskMessageEnvelope,
    TaskMessageHeader,
    TaskMessagePayload,
)
from src.core.task_contract.task_dispatcher_contract import (
    TaskDispatchDescriptor,
    TaskDispatchDescriptorHeader,
    TaskDispatchDescriptorPayload,
    TaskDispatchResultPayload,
)
from src.core.task_contract.task_registration_contract import (
    FunboostTaskRegistrationDetail,
    LocalTaskRegistrationDetail,
    TaskRegistrationEnvelope,
)


@dataclass(slots=True)
class TaskDispatchCommand:
    """
    任务分发命令。
    """

    payload: BaseModel
    job_kind: str | None = None
    retry_limit: int | None = None
    deduplication_key: str | None = None
    request_id: str | None = None
    trace_id: str | None = None


class DispatchBackgroundJobUsecase:
    """
    分发后台任务应用用例。
    """

    def __init__(self, *, task_runtime_port: TaskRuntimePort) -> None:
        """
        初始化分发后台任务用例。
        """

        self._task_runtime_port = task_runtime_port

    def execute(self, command: TaskDispatchCommand) -> TaskDispatchResultPayload:
        """
        执行分发后台任务主流程。
        """

        resolved_job_kind = command.job_kind or self._task_runtime_port.get_default_job_kind()
        runtime_backend = self._task_runtime_port.get_current_task_backend()
        registration = self._task_runtime_port.get_enabled_task_registration_for_backend(
            resolved_job_kind,
            backend=runtime_backend,
        )
        descriptor = self._build_dispatch_descriptor(
            command=command,
            registration=registration,
            default_retry_limit=self._task_runtime_port.get_default_retry_limit(),
        )
        task_message = self._build_task_message(descriptor, command=command)
        return self._task_runtime_port.dispatch_task_message(task_message)

    def _build_dispatch_descriptor(
        self,
        *,
        command: TaskDispatchCommand,
        registration: TaskRegistrationEnvelope,
        default_retry_limit: int,
    ) -> TaskDispatchDescriptor:
        """
        构建任务派发描述。
        """

        return TaskDispatchDescriptor(
            header=TaskDispatchDescriptorHeader(
                task_id=str(uuid.uuid4()),
                created_at_epoch=int(time.time()),
            ),
            payload=TaskDispatchDescriptorPayload(
                job_kind=registration.header.job_kind,
                payload_kind=command.payload.__class__.__name__,
                payload_json=command.payload.model_dump_json(),
                deduplication_key=(command.deduplication_key or str(uuid.uuid4())),
                retry_limit=self._resolve_retry_limit(
                    command=command,
                    default_retry_limit=default_retry_limit,
                    registration=registration,
                ),
            ),
        )

    def _build_task_message(
        self,
        descriptor: TaskDispatchDescriptor,
        *,
        command: TaskDispatchCommand,
    ) -> TaskMessageEnvelope:
        """
        基于派发描述构建任务消息。
        """

        return TaskMessageEnvelope(
            header=TaskMessageHeader(
                message_id=descriptor.header.task_id,
                request_id=command.request_id or str(uuid.uuid4()),
                trace_id=command.trace_id,
                created_at_epoch=descriptor.header.created_at_epoch,
            ),
            payload=TaskMessagePayload(
                job_kind=descriptor.payload.job_kind,
                deduplication_key=descriptor.payload.deduplication_key,
                retry_limit=descriptor.payload.retry_limit,
                payload_kind=descriptor.payload.payload_kind,
                payload_json=descriptor.payload.payload_json,
            ),
        )

    def _resolve_retry_limit(
        self,
        *,
        command: TaskDispatchCommand,
        default_retry_limit: int,
        registration: TaskRegistrationEnvelope,
    ) -> int:
        """
        解析任务重试次数。
        """

        if command.retry_limit is not None:
            return command.retry_limit
        if isinstance(registration.detail, FunboostTaskRegistrationDetail):
            return registration.detail.retry_limit
        if isinstance(registration.detail, LocalTaskRegistrationDetail):
            return registration.detail.retry_limit
        return default_retry_limit
