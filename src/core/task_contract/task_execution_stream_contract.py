"""管理员任务执行状态流业务契约。"""

from __future__ import annotations

from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from src.core.stream_contract.stream_event_contract import STREAM_SCHEMA_VERSION
from src.core.task_contract.task_execution_record_contract import TaskExecutionRecordEnvelope

TASK_EXECUTION_WATCH_COMMAND_KIND: Final = "task_execution_watch_command"
TASK_EXECUTION_SNAPSHOT_KIND: Final = "task_execution_snapshot"
TASK_EXECUTION_STREAM_TEXT_MINIMUM_LENGTH = 1
TASK_EXECUTION_POLL_INTERVAL_MINIMUM_SECONDS = 0.1
TASK_EXECUTION_POLL_INTERVAL_MAXIMUM_SECONDS = 30.0
TASK_EXECUTION_MAXIMUM_SNAPSHOTS = 1000


class TaskExecutionWatchCommand(BaseModel):
    """任务执行状态流订阅命令。"""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["task_execution_watch_command"] = TASK_EXECUTION_WATCH_COMMAND_KIND
    schema_version: Literal["1.0"] = STREAM_SCHEMA_VERSION
    task_id: str = Field(min_length=TASK_EXECUTION_STREAM_TEXT_MINIMUM_LENGTH)
    poll_interval_seconds: float = Field(
        ge=TASK_EXECUTION_POLL_INTERVAL_MINIMUM_SECONDS,
        le=TASK_EXECUTION_POLL_INTERVAL_MAXIMUM_SECONDS,
    )
    max_snapshots: int = Field(ge=1, le=TASK_EXECUTION_MAXIMUM_SNAPSHOTS)


class TaskExecutionSnapshotDetail(BaseModel):
    """任务执行状态流业务事件扩展。"""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["task_execution_snapshot"] = TASK_EXECUTION_SNAPSHOT_KIND
    schema_version: Literal["1.0"] = STREAM_SCHEMA_VERSION
    record: TaskExecutionRecordEnvelope
