"""
失败任务记录器基础设施模块。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from src.core.task_contract.task_dispatcher_contract import TaskFailureStage
from src.core.task_contract.task_runtime_contract import TaskBackend

FAILED_TASK_RECORDER_DEFAULT_MAX_ITEMS = 1000
FAILED_TASK_RECORDER_MIN_MAX_ITEMS = 1


@dataclass(slots=True)
class TaskFailureRecord:
    """
    任务失败记录数据对象。
    """

    task_id: str
    job_kind: str
    message: str
    retry_count: int
    backend: TaskBackend
    stage: TaskFailureStage
    last_error: str | None = None
    queue_name: str | None = None
    payload_kind: str | None = None
    request_id: str | None = None
    trace_id: str | None = None
    deduplication_key: str | None = None
    attempt_count: int = 0


class FailedTaskRecorder:
    """
    失败任务记录器。
    """

    def __init__(
        self,
        *,
        record_listener: Callable[[TaskFailureRecord], None] | None = None,
        max_items: int = FAILED_TASK_RECORDER_DEFAULT_MAX_ITEMS,
    ) -> None:
        """
        初始化失败任务记录器。
        """

        self._records: list[TaskFailureRecord] = []
        self._record_listener = record_listener
        self._max_items = max(max_items, FAILED_TASK_RECORDER_MIN_MAX_ITEMS)

    def record(self, record: TaskFailureRecord) -> None:
        """
        记录失败任务。
        """

        if len(self._records) >= self._max_items:
            self._records.pop(0)
        self._records.append(record)
        if self._record_listener is not None:
            self._record_listener(record)

    def list_records(self) -> list[TaskFailureRecord]:
        """
        列出失败任务记录集合。
        """

        return list(self._records)
