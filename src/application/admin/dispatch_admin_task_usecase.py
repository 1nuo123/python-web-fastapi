"""
管理员任务派发用例。
"""

from __future__ import annotations

from dataclasses import dataclass

from src.application.dispatch_background_job_usecase import (
    DispatchBackgroundJobUsecase,
    TaskDispatchCommand,
)
from src.application.ports.task_runtime_port import TaskRuntimePort
from src.core.task_contract.task_dispatcher_contract import TaskDispatchResultPayload


@dataclass(slots=True)
class AdminTaskDispatchCommand:
    """
    管理员任务派发命令。
    """

    job_kind: str
    payload_json: str
    retry_limit: int | None
    deduplication_key: str | None
    request_id: str | None
    trace_id: str | None


class DispatchAdminTaskUsecase:
    """
    管理员任务派发用例。
    """

    def __init__(
        self,
        *,
        task_runtime_port: TaskRuntimePort,
        dispatch_background_job_usecase: DispatchBackgroundJobUsecase,
    ) -> None:
        """
        初始化管理员任务派发用例。
        """

        self._task_runtime_port = task_runtime_port
        self._dispatch_background_job_usecase = dispatch_background_job_usecase

    def execute(
        self,
        command: AdminTaskDispatchCommand,
    ) -> TaskDispatchResultPayload:
        """
        执行管理员任务派发。
        """

        payload = self._task_runtime_port.validate_task_payload_json(
            job_kind=command.job_kind,
            payload_json=command.payload_json,
        )
        return self._dispatch_background_job_usecase.execute(
            TaskDispatchCommand(
                payload=payload,
                job_kind=command.job_kind,
                retry_limit=command.retry_limit,
                deduplication_key=command.deduplication_key,
                request_id=command.request_id,
                trace_id=command.trace_id,
            )
        )
