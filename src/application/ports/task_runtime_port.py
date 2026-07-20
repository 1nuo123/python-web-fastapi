"""
Task runtime application port.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel

from src.core.task_contract.message_bus_contract import (
    MessageBusBackend,
    TaskMessageEnvelope,
)
from src.core.task_contract.task_dispatcher_contract import TaskDispatchResultPayload
from src.core.task_contract.task_execution_record_contract import (
    TaskExecutionRecordEnvelope,
    TaskExecutionStatus,
)
from src.core.task_contract.task_registration_contract import TaskRegistrationEnvelope
from src.core.task_contract.task_runtime_contract import (
    MessageBackend,
    TaskBackend,
    TaskRuntimeMode,
)


@dataclass(slots=True)
class TaskRegistrationRuntimeSnapshot:
    """
    任务注册运行时快照。
    """

    registration: TaskRegistrationEnvelope
    handler_bound: bool
    payload_model_name: str | None
    registration_backend: TaskBackend
    current_runtime_backend: TaskBackend
    active_for_current_runtime: bool


class TaskRuntimePort(Protocol):
    """
    Application-facing task runtime capabilities.
    """

    def get_enabled_task_registration(self, job_kind: str) -> TaskRegistrationEnvelope:
        """
        Read an enabled task registration for the current backend.
        """

    def get_current_task_backend(self) -> TaskBackend:
        """
        Read the current task backend.
        """

    def get_current_configured_transport_backend(self) -> MessageBackend:
        """
        读取当前消息运行时配置后端。
        """

    def get_current_transport_backend(self) -> MessageBusBackend:
        """
        读取当前消息总线真实挂载后端。
        """

    def get_current_task_runtime_mode(self) -> TaskRuntimeMode:
        """
        读取当前任务运行时节点模式。
        """

    def is_task_worker_enabled(self) -> bool:
        """
        读取当前节点是否启用任务消费或工作器。
        """

    def is_local_inline_execute_enabled(self) -> bool:
        """
        读取当前本地任务后端是否启用内联执行。
        """

    def get_enabled_task_registration_for_backend(
        self,
        job_kind: str,
        *,
        backend: TaskBackend,
    ) -> TaskRegistrationEnvelope:
        """
        Read an enabled task registration for the specified backend.
        """

    def get_default_job_kind(self) -> str:
        """
        Read the default job kind.
        """

    def get_default_retry_limit(self) -> int:
        """
        Read the default retry limit.
        """

    def dispatch_task_message(
        self,
        task_message: TaskMessageEnvelope,
    ) -> TaskDispatchResultPayload:
        """
        Dispatch a task message.
        """

    def get_task_execution_record(
        self,
        task_id: str,
    ) -> TaskExecutionRecordEnvelope | None:
        """
        Read a task execution record by task id.
        """

    def list_task_execution_records(
        self,
        *,
        limit: int,
        status: TaskExecutionStatus | None = None,
        job_kind: str | None = None,
    ) -> list[TaskExecutionRecordEnvelope]:
        """
        List task execution records.
        """

    def list_task_registration_snapshots(self) -> list[TaskRegistrationRuntimeSnapshot]:
        """
        读取全部任务注册运行时快照。
        """

    def validate_task_payload_json(
        self,
        *,
        job_kind: str,
        payload_json: str,
    ) -> BaseModel:
        """
        按任务绑定的载荷模型校验 JSON 字符串。
        """
