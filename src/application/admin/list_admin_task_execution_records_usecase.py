"""
管理员任务执行记录列表用例。
"""

from __future__ import annotations

from dataclasses import dataclass

from src.application.ports.task_runtime_port import TaskRuntimePort
from src.core.task_contract.task_execution_record_contract import (
    TaskExecutionRecordEnvelope,
    TaskExecutionStatus,
)


@dataclass(slots=True)
class AdminTaskExecutionRecordListQuery:
    """
    管理员任务执行记录列表查询。
    """

    status: TaskExecutionStatus | None
    job_kind: str | None
    limit: int


class ListAdminTaskExecutionRecordsUsecase:
    """
    管理员任务执行记录列表用例。
    """

    def __init__(self, *, task_runtime_port: TaskRuntimePort) -> None:
        """
        初始化管理员任务执行记录列表用例。
        """

        self._task_runtime_port = task_runtime_port

    def execute(
        self,
        query: AdminTaskExecutionRecordListQuery,
    ) -> list[TaskExecutionRecordEnvelope]:
        """
        执行管理员任务执行记录列表查询。
        """

        return self._task_runtime_port.list_task_execution_records(
            limit=query.limit,
            status=query.status,
            job_kind=query.job_kind,
        )
