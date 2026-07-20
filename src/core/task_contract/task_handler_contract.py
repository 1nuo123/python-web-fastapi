"""
任务处理器契约核心契约模块。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Generic

from src.core.task_contract.task_invocation_contract import (
    TaskPayloadT,
    TypedTaskInvocation,
)


class TaskHandler(ABC, Generic[TaskPayloadT]):
    """
    任务处理器抽象基类，定义任务消费入口。
    """

    @abstractmethod
    def handle(self, invocation: TypedTaskInvocation[TaskPayloadT]) -> None:
        """
        处理任务执行对象。

        :param invocation: 任务执行对象。约束：需符合 ``TypedTaskInvocation`` 注解。
        :type invocation: TypedTaskInvocation[TaskPayloadT]
        :returns: 无返回值。
        :rtype: None
        """

        pass
