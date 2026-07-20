"""
任务工作器监督器基础设施模块。
"""

from __future__ import annotations

from pydantic import BaseModel

from src.core.task_contract.task_handler_contract import TaskHandler
from src.infrastructure.task.task_registration_registry import RegisteredTaskBinding


class TaskWorkerSupervisor:
    """
    任务工作器监督器，负责管理任务处理器注册。
    """

    def __init__(self) -> None:
        """
        初始化任务工作器监督器。
        """

        self._bindings: dict[str, RegisteredTaskBinding[BaseModel]] = {}

    def register_handler(
        self,
        *,
        job_kind: str,
        payload_model: type[BaseModel],
        handler: TaskHandler[BaseModel],
    ) -> None:
        """
        注册处理器。
        """

        self.register_binding(
            RegisteredTaskBinding(
                job_kind=job_kind,
                payload_model=payload_model,
                handler=handler,
            )
        )

    def register_binding(self, binding: RegisteredTaskBinding[BaseModel]) -> None:
        """
        注册任务绑定。
        """

        self._bindings[binding.job_kind] = binding

    def get_handler(self, job_kind: str) -> TaskHandler[BaseModel] | None:
        """
        获取处理器。
        """

        binding = self._bindings.get(job_kind)
        if binding is None:
            return None
        return binding.handler

    def get_binding(self, job_kind: str) -> RegisteredTaskBinding[BaseModel] | None:
        """
        获取任务绑定。
        """

        return self._bindings.get(job_kind)

    def list_bindings(self) -> list[RegisteredTaskBinding[BaseModel]]:
        """
        列出全部任务绑定。
        """

        return list(self._bindings.values())

    def replace_bindings(self, bindings: list[RegisteredTaskBinding[BaseModel]]) -> None:
        """
        替换任务绑定集合。
        """

        self._bindings = {binding.job_kind: binding for binding in bindings}
