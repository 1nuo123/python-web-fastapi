"""
测试日志器工厂单元测试模块。
"""

from __future__ import annotations

import logging
from logging import LogRecord

from src.core.logging_contract.log_writer_contract import LogWriteRequest, LogWriteResult
from src.infrastructure.logging.app_logger_factory import AppLoggerFactory
from src.infrastructure.logging.log_buffer_dispatcher import LogBufferDispatcher
from src.infrastructure.logging.structured_log_handler import StructuredLogHandler
from src.infrastructure.settings.app_settings_loader import AppSettingsLoader
from src.infrastructure.settings.application_settings import AppEnvironment

LOGGER_FACTORY_BUFFER_MAX_ITEMS = 10
LOGGER_FACTORY_FLUSH_INTERVAL_SECONDS = 100


class FakeWriter:
    """
    伪日志写入器。
    """

    def write_batch(self, request: LogWriteRequest) -> LogWriteResult:
        """
        写入批次。
        """

        return LogWriteResult(
            written_count=len(request.events),
            failed_count=0,
            degraded_to_stdout=False,
            failure_reason=None,
        )


class TestLoggerFactoryUnit:
    """
    测试日志器工厂单元测试集合，用于组织同一主题下的测试场景。
    """

    def test_logger_factory_should_build_stream_logger(self) -> None:
        """
        验证日志器工厂应构建标准输出日志器。
        """

        settings = AppSettingsLoader().load_for_environment(AppEnvironment.TEST)
        logger = AppLoggerFactory().build(settings)
        assert logger.level == logging.DEBUG
        assert logger.handlers

    def test_logger_factory_should_configure_structured_handler(self) -> None:
        """
        验证日志器工厂应配置结构化处理器。
        """

        settings = AppSettingsLoader().load_for_environment(AppEnvironment.TEST)
        logger_factory = AppLoggerFactory()
        logger = logger_factory.build(settings)
        dispatcher = LogBufferDispatcher(
            writer=FakeWriter(),
            logger=logger,
            buffer_max_items=LOGGER_FACTORY_BUFFER_MAX_ITEMS,
            flush_interval_seconds=LOGGER_FACTORY_FLUSH_INTERVAL_SECONDS,
            max_batch_size=LOGGER_FACTORY_BUFFER_MAX_ITEMS,
        )
        try:
            handler = StructuredLogHandler(dispatcher)
            logger_factory.configure_structured_handler(logger, handler)
            assert any(isinstance(item, StructuredLogHandler) for item in logger.handlers)
        finally:
            logger_factory.remove_structured_handlers(logger)
            dispatcher.shutdown()

    def test_stream_handler_formatter_should_redact_sensitive_message(self) -> None:
        """
        验证默认标准输出日志格式化器应脱敏敏感文本。

        :returns: 无返回值。
        :rtype: None
        """

        settings = AppSettingsLoader().load_for_environment(AppEnvironment.TEST)
        logger = AppLoggerFactory().build(settings)
        stream_handler = next(
            handler for handler in logger.handlers if handler.get_name() == "default_stream_handler"
        )
        formatter = stream_handler.formatter
        if formatter is None:
            raise AssertionError("默认日志处理器缺少格式化器。")
        record = LogRecord(
            name="fastapi_web_skeleton",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="Bearer abc.def.ghi password=plain postgresql://u:p@db/app",
            args=(),
            exc_info=None,
        )

        formatted_message = formatter.format(record)

        assert "plain" not in formatted_message
        assert "abc.def.ghi" not in formatted_message
        assert "p@db" not in formatted_message
