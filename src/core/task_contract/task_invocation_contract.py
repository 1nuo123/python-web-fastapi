"""
任务执行契约核心模块。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Generic, TypeVar

from pydantic import BaseModel

from src.core.task_contract.message_bus_contract import TaskMessageEnvelope

if TYPE_CHECKING:
    from src.core.task_contract.task_handler_contract import TaskHandler

TASK_INVOCATION_KIND = "task_invocation"
TASK_INVOCATION_SCHEMA_VERSION = "1.0"
TASK_BINDING_KIND = "task_invocation_binding"
TASK_BINDING_SCHEMA_VERSION = "1.0"

TaskPayloadT = TypeVar("TaskPayloadT", bound=BaseModel)


@dataclass(slots=True, frozen=True)
class TaskInvocationBinding(Generic[TaskPayloadT]):
    """
    任务执行绑定对象。
    """

    job_kind: str
    payload_model: type[TaskPayloadT]
    handler: TaskHandler[TaskPayloadT]
    kind: str = field(init=False, default=TASK_BINDING_KIND)
    schema_version: str = field(init=False, default=TASK_BINDING_SCHEMA_VERSION)


@dataclass(slots=True, frozen=True, kw_only=True)
class TypedTaskInvocation(Generic[TaskPayloadT]):
    """
    任务执行信封对象。
    """

    payload: TaskPayloadT
    message: TaskMessageEnvelope
    binding: TaskInvocationBinding[TaskPayloadT]
    kind: str = field(init=False, default=TASK_INVOCATION_KIND)
    schema_version: str = field(init=False, default=TASK_INVOCATION_SCHEMA_VERSION)


TaskInvocationResolution = TypedTaskInvocation
