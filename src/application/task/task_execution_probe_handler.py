"""任务执行探针处理器。"""

from __future__ import annotations

from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from src.core.task_contract.task_handler_contract import TaskHandler
from src.core.task_contract.task_invocation_contract import TypedTaskInvocation

TASK_EXECUTION_PROBE_PAYLOAD_KIND: Final = "task_execution_probe"
TASK_EXECUTION_PROBE_SCHEMA_VERSION: Final = "1.0"
TASK_EXECUTION_PROBE_ID_MINIMUM_LENGTH = 1


class TaskExecutionProbePayload(BaseModel):
    """生产任务执行探针载荷。

    :ivar kind: 载荷判别值。
    :ivar schema_version: 载荷结构版本。
    :ivar probe_id: 业务探针标识。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["task_execution_probe"] = TASK_EXECUTION_PROBE_PAYLOAD_KIND
    schema_version: Literal["1.0"] = TASK_EXECUTION_PROBE_SCHEMA_VERSION
    probe_id: str = Field(min_length=TASK_EXECUTION_PROBE_ID_MINIMUM_LENGTH)


class TaskExecutionProbeHandler(TaskHandler[TaskExecutionProbePayload]):
    """执行生产任务消费探针并交由运行时持久化结果。"""

    def handle(self, invocation: TypedTaskInvocation[TaskExecutionProbePayload]) -> None:
        """完成强类型探针校验。

        探针的业务结果是任务运行时持久化的 ``SUCCESS`` 执行记录。处理器仅负责
        应用层强类型校验，不越过任务运行时重复写执行状态。

        :param invocation: 统一任务调用对象。
        :type invocation: TypedTaskInvocation[TaskExecutionProbePayload]
        :returns: 无返回值。
        :rtype: None
        """

        if invocation.payload.probe_id != invocation.message.payload.deduplication_key:
            raise ValueError("任务执行探针标识必须与幂等键一致。")
