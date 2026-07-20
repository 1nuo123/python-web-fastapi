"""
管理员任务注册列表用例。
"""

from __future__ import annotations

from src.application.ports.task_runtime_port import (
    TaskRegistrationRuntimeSnapshot,
    TaskRuntimePort,
)


class ListAdminTaskRegistrationsUsecase:
    """
    管理员任务注册列表用例。
    """

    def __init__(self, *, task_runtime_port: TaskRuntimePort) -> None:
        """
        初始化管理员任务注册列表用例。
        """

        self._task_runtime_port = task_runtime_port

    def execute(self) -> list[TaskRegistrationRuntimeSnapshot]:
        """
        执行管理员任务注册列表查询。
        """

        return self._task_runtime_port.list_task_registration_snapshots()
