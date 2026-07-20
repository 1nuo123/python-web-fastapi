"""
结构化日志处理器模块。
"""

from __future__ import annotations

import logging

from src.core.logging_contract.log_event_contract import LogEventEnvelope
from src.infrastructure.logging.log_buffer_dispatcher import LogBufferDispatcher


class StructuredLogHandler(logging.Handler):
    """
    结构化日志处理器。
    """

    def __init__(self, dispatcher: LogBufferDispatcher) -> None:
        """
        初始化结构化日志处理器。

        :param dispatcher: 日志缓冲派发器。
        :type dispatcher: LogBufferDispatcher
        :returns: 无返回值。
        :rtype: None
        """

        super().__init__()
        self._dispatcher = dispatcher

    def emit(self, record: logging.LogRecord) -> None:
        """
        处理标准 logging 记录。

        :param record: 标准日志记录对象。
        :type record: logging.LogRecord
        :returns: 无返回值。
        :rtype: None
        """

        event = getattr(record, "structured_event", None)
        if isinstance(event, LogEventEnvelope):
            self._dispatcher.emit(event)

    def emit_event(self, event: LogEventEnvelope) -> None:
        """
        直接处理结构化日志事件。

        :param event: 日志事件信封。
        :type event: LogEventEnvelope
        :returns: 无返回值。
        :rtype: None
        """

        self._dispatcher.emit(event)
