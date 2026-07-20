"""
应用日志器工厂基础设施模块。
"""

from __future__ import annotations

import logging

from src.infrastructure.logging.sensitive_text_redactor import SensitiveTextRedactor
from src.infrastructure.logging.structured_log_handler import StructuredLogHandler
from src.infrastructure.settings.application_settings import ApplicationSettings

APPLICATION_LOGGER_NAME = "fastapi_web_skeleton"
DEFAULT_LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
STREAM_HANDLER_NAME = "default_stream_handler"
STRUCTURED_HANDLER_NAME = "structured_database_handler"


class RedactingLogFormatter(logging.Formatter):
    """
    脱敏日志格式化器。

    :param fmt: 日志格式模板。
    :type fmt: str
    """

    def __init__(self, fmt: str) -> None:
        """
        初始化脱敏日志格式化器。

        :param fmt: 日志格式模板。
        :type fmt: str
        :returns: 无返回值。
        :rtype: None
        """

        super().__init__(fmt)
        self._redactor = SensitiveTextRedactor()

    def format(self, record: logging.LogRecord) -> str:
        """
        格式化并脱敏日志文本。

        :param record: 日志记录。
        :type record: logging.LogRecord
        :returns: 已脱敏日志文本。
        :rtype: str
        """

        formatted_message = super().format(record)
        return self._redactor.redact(formatted_message) or ""


class AppLoggerFactory:
    """
    应用日志器工厂，负责构建目标对象。
    """

    def build(self, settings: ApplicationSettings) -> logging.Logger:
        """
        处理构建。

        :param settings: 已经通过校验的应用配置快照。约束：需符合 ``ApplicationSettings`` 注解。
        :type settings: ApplicationSettings
        :returns: 返回当前操作结果。
        :rtype: logging.Logger
        """

        logger = logging.getLogger(APPLICATION_LOGGER_NAME)
        logger.setLevel(settings.runtime.logging.level.value)
        self._ensure_stream_handler(logger)
        logger.propagate = False
        return logger

    def update_level(self, logger: logging.Logger, level: str) -> None:
        """
        更新级别。

        :param logger: 当前组件使用的日志记录器。约束：需符合 ``logging.Logger`` 注解。
        :type logger: logging.Logger
        :param level: 日志级别字符串。约束：需符合 ``str`` 注解。
        :type level: str
        :returns: 无返回值。
        :rtype: None
        """

        logger.setLevel(level)

    def configure_structured_handler(
        self,
        logger: logging.Logger,
        handler: StructuredLogHandler,
    ) -> None:
        """
        配置结构化日志处理器。

        :param logger: 当前组件使用的日志记录器。约束：需符合 ``logging.Logger`` 注解。
        :type logger: logging.Logger
        :param handler: 结构化日志处理器。约束：需符合 ``StructuredLogHandler`` 注解。
        :type handler: StructuredLogHandler
        :returns: 无返回值。
        :rtype: None
        """

        self.remove_structured_handlers(logger)
        handler.set_name(STRUCTURED_HANDLER_NAME)
        logger.addHandler(handler)

    def remove_structured_handlers(self, logger: logging.Logger) -> None:
        """
        移除结构化日志处理器。

        :param logger: 当前组件使用的日志记录器。约束：需符合 ``logging.Logger`` 注解。
        :type logger: logging.Logger
        :returns: 无返回值。
        :rtype: None
        """

        for handler in list(logger.handlers):
            if not isinstance(handler, StructuredLogHandler):
                continue
            logger.removeHandler(handler)
            handler.close()

    def _ensure_stream_handler(self, logger: logging.Logger) -> None:
        """
        确保标准输出处理器存在且格式稳定。

        :param logger: 当前组件使用的日志记录器。约束：需符合 ``logging.Logger`` 注解。
        :type logger: logging.Logger
        :returns: 无返回值。
        :rtype: None
        """

        for handler in logger.handlers:
            if handler.get_name() == STREAM_HANDLER_NAME:
                if not isinstance(handler.formatter, RedactingLogFormatter):
                    handler.setFormatter(RedactingLogFormatter(DEFAULT_LOG_FORMAT))
                return
        stream_handler = logging.StreamHandler()
        stream_handler.set_name(STREAM_HANDLER_NAME)
        stream_handler.setFormatter(RedactingLogFormatter(DEFAULT_LOG_FORMAT))
        logger.addHandler(stream_handler)
