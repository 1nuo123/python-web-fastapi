"""
管理员任务运行时读取用例。
"""

from __future__ import annotations

from dataclasses import dataclass

from src.application.ports.task_runtime_port import TaskRuntimePort
from src.core.task_contract.message_bus_contract import MessageBusBackend
from src.core.task_contract.task_runtime_contract import (
    MessageBackend,
    TaskBackend,
    TaskRuntimeMode,
)


@dataclass(slots=True)
class AdminTaskRuntimeResult:
    """
    管理员任务运行时结果。
    """

    task_runtime_mode: TaskRuntimeMode
    task_backend: TaskBackend
    transport_backend: MessageBusBackend
    configured_transport_backend: MessageBackend
    worker_enabled: bool
    inline_execute_enabled: bool
    default_job_kind: str
    default_retry_limit: int


class ReadAdminTaskRuntimeUsecase:
    """
    管理员任务运行时读取用例。
    """

    def __init__(self, *, task_runtime_port: TaskRuntimePort) -> None:
        """
        初始化管理员任务运行时读取用例。
        """

        self._task_runtime_port = task_runtime_port

    def execute(self) -> AdminTaskRuntimeResult:
        """
        执行管理员任务运行时读取。
        """

        return AdminTaskRuntimeResult(
            task_runtime_mode=self._task_runtime_port.get_current_task_runtime_mode(),
            task_backend=self._task_runtime_port.get_current_task_backend(),
            transport_backend=self._task_runtime_port.get_current_transport_backend(),
            configured_transport_backend=(
                self._task_runtime_port.get_current_configured_transport_backend()
            ),
            worker_enabled=self._task_runtime_port.is_task_worker_enabled(),
            inline_execute_enabled=(self._task_runtime_port.is_local_inline_execute_enabled()),
            default_job_kind=self._task_runtime_port.get_default_job_kind(),
            default_retry_limit=self._task_runtime_port.get_default_retry_limit(),
        )
