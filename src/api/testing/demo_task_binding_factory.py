"""
API 测试示例任务绑定工厂模块。
"""

from __future__ import annotations

from typing import cast

from pydantic import BaseModel, ConfigDict

from src.core.task_contract.task_handler_contract import TaskHandler
from src.core.task_contract.task_invocation_contract import (
    TypedTaskInvocation,
)
from src.infrastructure.task.task_registration_registry import (
    BaseModelTaskBinding,
    RegisteredTaskBinding,
)

DEMO_TASK_KIND = "demo_task"
DEMO_FUNBOOST_TASK_KIND = "demo_task_funboost"
DEMO_PAYLOAD_KIND = "demo_task"
DEMO_SCHEMA_VERSION = "1.0"
DEMO_TASK_ID = "default-demo-task"


class DemoTaskPayload(BaseModel):
    """
    测试示例任务载荷模型。
    """

    model_config = ConfigDict(extra="forbid")

    kind: str = DEMO_PAYLOAD_KIND
    schema_version: str = DEMO_SCHEMA_VERSION
    task_id: str = DEMO_TASK_ID


class NoopTaskHandler(TaskHandler[DemoTaskPayload]):
    """
    测试示例空任务处理器。
    """

    def handle(self, invocation: TypedTaskInvocation[DemoTaskPayload]) -> None:
        """
        执行空任务处理。
        """

        _ = invocation
        return None


class DemoTaskBindingFactory:
    """
    测试示例任务绑定工厂。
    """

    def build(self) -> list[BaseModelTaskBinding]:
        """
        构建测试示例任务绑定集合。
        """

        return [
            cast(
                BaseModelTaskBinding,
                RegisteredTaskBinding(
                    job_kind=DEMO_TASK_KIND,
                    payload_model=DemoTaskPayload,
                    handler=NoopTaskHandler(),
                ),
            ),
            cast(
                BaseModelTaskBinding,
                RegisteredTaskBinding(
                    job_kind=DEMO_FUNBOOST_TASK_KIND,
                    payload_model=DemoTaskPayload,
                    handler=NoopTaskHandler(),
                ),
            ),
        ]
