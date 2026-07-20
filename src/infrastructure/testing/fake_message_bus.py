"""
模拟消息总线基础设施模块。
"""

from __future__ import annotations

from src.core.task_contract.message_bus_contract import (
    MessageBus,
    MessageBusBackend,
    MessagePublishResult,
    TaskMessageEnvelope,
)


class FakeMessageBus(MessageBus):
    """
    模拟消息总线类型，用于封装当前模块中的相关行为或状态。
    """

    def __init__(self) -> None:
        """
        初始化模拟消息总线。

        :returns: 无返回值。
        :rtype: None
        """

        self.messages: list[TaskMessageEnvelope] = []

    def publish(self, message: TaskMessageEnvelope) -> MessagePublishResult:
        """
        发布当前消息。

        :param message: 消息对象或消息文本。约束：需符合 ``TaskMessageEnvelope`` 注解。
        :type message: TaskMessageEnvelope
        :returns: 消息发布结果。
        :rtype: MessagePublishResult
        """

        self.messages.append(message)
        return MessagePublishResult.build_succeeded(
            message_id=message.header.message_id,
            routed=True,
        )

    @property
    def backend(self) -> MessageBusBackend:
        """
        读取模拟消息总线后端标识。
        """

        return MessageBusBackend.LOCAL

    def close(self) -> None:
        """
        关闭模拟消息总线。
        """

        return None
