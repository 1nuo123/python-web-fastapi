"""
任务分发器契约核心模块。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from src.core.task_contract.message_bus_contract import TaskMessageEnvelope
from src.core.task_contract.task_execution_record_contract import (
    TaskExecutionStage,
    TaskExecutionStatus,
)
from src.core.task_contract.task_runtime_contract import TaskBackend

TASK_DISPATCH_SCHEMA_VERSION = "1.0"
TASK_DISPATCH_RESULT_KIND = "task_dispatch_result"
TASK_DISPATCH_DESCRIPTOR_HEADER_KIND = "task_dispatch_descriptor_header"
TASK_DISPATCH_DESCRIPTOR_PAYLOAD_KIND = "task_dispatch_descriptor"


class TaskFailureStage(StrEnum):
    """
    任务失败阶段枚举。
    """

    STARTUP_PROBE = "startup_probe"
    DISPATCH_PUBLISH = "dispatch_publish"
    LOCAL_EXECUTION = "local_execution"
    CONSUME_EXECUTION = "consume_execution"


class TaskDispatchDescriptorHeader(BaseModel):
    """
    任务派发描述公共头。
    """

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(default=TASK_DISPATCH_DESCRIPTOR_HEADER_KIND)
    schema_version: str = Field(default=TASK_DISPATCH_SCHEMA_VERSION)
    task_id: str
    created_at_epoch: int


class TaskDispatchDescriptorPayload(BaseModel):
    """
    任务派发描述扩展体。
    """

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(default=TASK_DISPATCH_DESCRIPTOR_PAYLOAD_KIND)
    schema_version: str = Field(default=TASK_DISPATCH_SCHEMA_VERSION)
    job_kind: str
    payload_kind: str
    payload_json: str
    deduplication_key: str
    retry_limit: int


class TaskDispatchDescriptor(BaseModel):
    """
    任务派发描述。
    """

    model_config = ConfigDict(extra="forbid")

    header: TaskDispatchDescriptorHeader
    payload: TaskDispatchDescriptorPayload


class TaskDispatchResultPayload(BaseModel):
    """
    任务分发结果模型。
    """

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(default=TASK_DISPATCH_RESULT_KIND)
    schema_version: str = Field(default=TASK_DISPATCH_SCHEMA_VERSION)
    task_id: str
    job_kind: str
    dispatched: bool
    retry_limit: int
    backend: TaskBackend
    queue_name: str
    published: bool
    worker_enabled: bool
    inline_execute_enabled: bool | None = None
    execution_status: TaskExecutionStatus
    execution_stage: TaskExecutionStage
    reused_existing_record: bool = False


class TaskDispatcher(ABC):
    """
    任务分发器抽象基类。
    """

    @abstractmethod
    def dispatch(self, message: TaskMessageEnvelope) -> TaskDispatchResultPayload:
        """
        分发任务消息。
        """

    @abstractmethod
    def shutdown(self) -> None:
        """
        关闭任务分发器持有的底层资源。
        """
