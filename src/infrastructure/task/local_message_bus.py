"""
本地消息总线基础设施模块。
"""

from __future__ import annotations

import threading

from src.core.task_contract.message_bus_contract import (
    MessageBus,
    MessageBusBackend,
    MessagePublishResult,
    TaskMessageEnvelope,
)

LOCAL_MESSAGE_BUS_DEFAULT_MAX_ITEMS = 1000
LOCAL_MESSAGE_BUS_MIN_MAX_ITEMS = 1
LOCAL_MESSAGE_BUS_CAPACITY_EXHAUSTED_MESSAGE = "本地消息队列容量已耗尽。"


class LocalMessageBus(MessageBus):
    """
    本地消息总线类型，用于封装当前模块中的相关行为或状态。
    """

    def __init__(
        self,
        *,
        max_items: int = LOCAL_MESSAGE_BUS_DEFAULT_MAX_ITEMS,
    ) -> None:
        """
        初始化本地消息总线。

        :param max_items: 本地保留消息数量上限。
        :type max_items: int
        :returns: 无返回值。
        :rtype: None
        """

        self._messages: list[TaskMessageEnvelope] = []
        self._max_items = max(max_items, LOCAL_MESSAGE_BUS_MIN_MAX_ITEMS)
        self._lock = threading.RLock()

    def publish(self, message: TaskMessageEnvelope) -> MessagePublishResult:
        """
        发布当前消息。

        :param message: 消息对象或消息文本。约束：需符合 ``TaskMessageEnvelope`` 注解。
        :type message: TaskMessageEnvelope
        :returns: 消息发布结果。
        :rtype: MessagePublishResult
        """

        with self._lock:
            if any(
                queued_message.header.message_id == message.header.message_id
                for queued_message in self._messages
            ):
                return MessagePublishResult.build_succeeded(
                    message_id=message.header.message_id,
                    routed=True,
                )
            if len(self._messages) >= self._max_items:
                return MessagePublishResult.build_failed(
                    message_id=message.header.message_id,
                    failure_reason=LOCAL_MESSAGE_BUS_CAPACITY_EXHAUSTED_MESSAGE,
                )
            self._messages.append(message)
            return MessagePublishResult.build_succeeded(
                message_id=message.header.message_id,
                routed=True,
            )

    @property
    def backend(self) -> MessageBusBackend:
        """
        读取消息总线后端标识。

        :returns: 本地消息总线后端。
        :rtype: MessageBusBackend
        """

        return MessageBusBackend.LOCAL

    def close(self) -> None:
        """
        关闭本地消息总线。

        :returns: 无返回值。
        :rtype: None
        """

        return None

    def list_messages(self) -> list[TaskMessageEnvelope]:
        """
        列出消息集合。

        :returns: 返回按实现构造的列表结果。
        :rtype: list[TaskMessageEnvelope]
        """

        with self._lock:
            return list(self._messages)

    def read_queue_depth(self) -> int:
        """
        读取当前保留消息数量。

        :returns: 本地队列当前消息数量。
        :rtype: int
        """

        with self._lock:
            return len(self._messages)
