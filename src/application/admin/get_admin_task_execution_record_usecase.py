"""
管理员任务执行记录详情用例。
"""

from __future__ import annotations

from http import HTTPStatus

from src.application.ports.task_runtime_port import TaskRuntimePort
from src.core.exception_contract.error_code_catalog_contract import CoreErrorCode
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.task_contract.task_execution_record_contract import (
    TaskExecutionRecordEnvelope,
)

ADMIN_TASK_EXECUTION_RECORD_NOT_FOUND_MESSAGE = "任务执行记录不存在。"


class GetAdminTaskExecutionRecordUsecase:
    """
    管理员任务执行记录详情用例。
    """

    def __init__(self, *, task_runtime_port: TaskRuntimePort) -> None:
        """
        初始化管理员任务执行记录详情用例。
        """

        self._task_runtime_port = task_runtime_port

    def execute(self, *, task_id: str) -> TaskExecutionRecordEnvelope:
        """
        执行管理员任务执行记录详情查询。
        """

        record = self._task_runtime_port.get_task_execution_record(task_id)
        if record is None:
            raise HttpFaultException(
                status_code=HTTPStatus.NOT_FOUND,
                error_code=CoreErrorCode.REQUEST_INVALID,
                message=ADMIN_TASK_EXECUTION_RECORD_NOT_FOUND_MESSAGE,
                detail=task_id,
            )
        return record
