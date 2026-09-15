"""消息传输资源的唯一生命周期 owner。"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING
from weakref import WeakValueDictionary

if TYPE_CHECKING:
    from src.core.task_contract.message_bus_contract import MessageBus


class MessageResourceOwner:
    """持有并幂等关闭消息总线，避免多个运行时入口重复释放。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._active: MessageBus | None = None
        self._closed: WeakValueDictionary[int, MessageBus] = WeakValueDictionary()

    def attach(self, message_bus: MessageBus) -> None:
        """登记当前活动消息总线。"""

        with self._lock:
            self._active = message_bus

    def detach(self) -> MessageBus | None:
        """移除当前活动消息总线并返回句柄。"""

        with self._lock:
            message_bus = self._active
            self._active = None
            return message_bus

    def close(self, message_bus: MessageBus | None = None) -> None:
        """关闭指定或当前消息总线；同一对象只调用一次 close。"""

        with self._lock:
            target = message_bus if message_bus is not None else self._active
            if target is None:
                return
            if target is self._active:
                self._active = None
            target_id = id(target)
            if self._closed.get(target_id) is target:
                return
            self._closed[target_id] = target
        target.close()
