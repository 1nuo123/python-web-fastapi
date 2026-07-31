"""管理员任务执行状态流事件源。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from http import HTTPStatus

from src.application.ports.stream_event_source_port import StreamExecutionContext
from src.application.ports.task_runtime_port import TaskRuntimePort
from src.core.exception_contract.error_code_catalog_contract import CoreErrorCode
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.task_contract.task_execution_record_contract import TaskExecutionStatus
from src.core.task_contract.task_execution_stream_contract import (
    TaskExecutionSnapshotDetail,
    TaskExecutionWatchCommand,
)

TASK_EXECUTION_STREAM_RECORD_NOT_FOUND_MESSAGE = "任务执行记录不存在。"
TASK_EXECUTION_TERMINAL_STATUSES = frozenset(
    {TaskExecutionStatus.SUCCESS, TaskExecutionStatus.FAILED}
)


class TaskExecutionStreamSource:
    """复用任务运行时事实源并产生状态变化事件。"""

    def __init__(self, *, task_runtime_port: TaskRuntimePort) -> None:
        """初始化任务执行状态流事件源。"""

        self._task_runtime_port = task_runtime_port

    async def open(
        self,
        *,
        command: TaskExecutionWatchCommand,
        context: StreamExecutionContext,
    ) -> AsyncGenerator[TaskExecutionSnapshotDetail, None]:
        """按状态变化产生任务执行快照。"""

        previous_snapshot_json: str | None = None
        for _snapshot_index in range(command.max_snapshots):
            record = await asyncio.to_thread(
                self._task_runtime_port.get_task_execution_record,
                command.task_id,
            )
            if record is None:
                raise HttpFaultException(
                    status_code=HTTPStatus.NOT_FOUND,
                    error_code=CoreErrorCode.REQUEST_INVALID,
                    message=TASK_EXECUTION_STREAM_RECORD_NOT_FOUND_MESSAGE,
                )
            snapshot_json = record.model_dump_json()
            if snapshot_json != previous_snapshot_json:
                yield TaskExecutionSnapshotDetail(record=record)
                previous_snapshot_json = snapshot_json
            if record.detail.status in TASK_EXECUTION_TERMINAL_STATUSES:
                return
            await asyncio.sleep(command.poll_interval_seconds)
