"""
应用任务绑定提供器模块。

当前文件是业务项目注入任务处理器绑定的显式扩展点，并为生产配置中启用的任务执行
探针提供可执行处理器绑定。
"""

from __future__ import annotations

from typing import cast

from src.application.task.task_execution_probe_handler import (
    TaskExecutionProbeHandler,
    TaskExecutionProbePayload,
)
from src.infrastructure.task.task_registration_registry import (
    BaseModelTaskBinding,
    RegisteredTaskBinding,
)

TASK_EXECUTION_PROBE_JOB_KIND = "task_execution_probe"


class ApplicationTaskBindingProvider:
    """
    应用任务绑定提供器。

    业务项目需要启用 ``modules.task.registrations`` 中声明的任务时，应在此处返回对应的
    ``RegisteredTaskBinding``，或在测试工厂中显式注入绑定。
    """

    def build(self) -> list[BaseModelTaskBinding]:
        """
        构建应用显式任务绑定集合。

        返回生产配置已声明的任务执行探针绑定。新增启用任务仍必须在此提供同名
        ``job_kind`` 处理器，否则消费者节点按缺失处理器拒绝启动。
        """

        return [
            cast(
                BaseModelTaskBinding,
                RegisteredTaskBinding(
                    job_kind=TASK_EXECUTION_PROBE_JOB_KIND,
                    payload_model=TaskExecutionProbePayload,
                    handler=TaskExecutionProbeHandler(),
                ),
            )
        ]
