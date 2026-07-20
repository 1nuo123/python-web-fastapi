"""
日志运行时配置契约模块。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.core.logging_contract.log_event_contract import LogLevel

LOG_RUNTIME_SCHEMA_VERSION: Final = "1.0"
DATABASE_LOG_SINK_KIND: Final = "database"
LOGGING_ENTRY_PROJECT_NAME_ENVIRONMENT_VARIABLE = "LOGGING_ENTRY_PROJECT_NAME"
LOGGING_ENTRY_LOG_PATH_ENVIRONMENT_VARIABLE = "LOGGING_ENTRY_LOG_PATH"
BUFFER_MAX_ITEMS_MINIMUM = 1
FLUSH_INTERVAL_SECONDS_MINIMUM = 1
MAX_BATCH_SIZE_MINIMUM = 1
RETENTION_DAYS_MINIMUM = 1
TABLE_NAME_MINIMUM_LENGTH = 1
ENTRY_PROJECT_NAME_MINIMUM_LENGTH = 1
ENTRY_LOG_PATH_MINIMUM_LENGTH = 1


class LogSink(StrEnum):
    """
    日志落库目标枚举。
    """

    DATABASE = DATABASE_LOG_SINK_KIND


class DatabaseLogSinkDetail(BaseModel):
    """
    数据库日志扩展配置模型。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["database"] = DATABASE_LOG_SINK_KIND
    schema_version: Literal["1.0"] = LOG_RUNTIME_SCHEMA_VERSION
    table_name: str = Field(min_length=TABLE_NAME_MINIMUM_LENGTH)
    flush_interval_seconds: int = Field(ge=FLUSH_INTERVAL_SECONDS_MINIMUM)
    max_batch_size: int = Field(ge=MAX_BATCH_SIZE_MINIMUM)
    fallback_to_stdout: bool
    retention_days: int = Field(ge=RETENTION_DAYS_MINIMUM)


LogSinkDetailUnion = Annotated[
    DatabaseLogSinkDetail,
    Field(discriminator="kind"),
]


class LoggingRuntimeSettings(BaseModel):
    """
    日志运行时配置模型。
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool
    level: LogLevel
    sink: LogSink
    buffer_max_items: int = Field(ge=BUFFER_MAX_ITEMS_MINIMUM)
    entry_project_name: str = Field(min_length=ENTRY_PROJECT_NAME_MINIMUM_LENGTH)
    entry_log_path: str = Field(min_length=ENTRY_LOG_PATH_MINIMUM_LENGTH)
    sink_detail: LogSinkDetailUnion

    @model_validator(mode="after")
    def validate_sink_detail(self) -> LoggingRuntimeSettings:
        """
        校验日志公共配置与扩展配置的一致性。

        :returns: 当前模型实例。
        :rtype: LoggingRuntimeSettings
        :raises ValueError: 当外层 sink 与内层 kind 不一致时抛出。
        """

        if self.sink == LogSink.DATABASE and not isinstance(
            self.sink_detail,
            DatabaseLogSinkDetail,
        ):
            raise ValueError(
                "runtime.logging.sink 为 database 时，sink_detail 必须是数据库日志扩展配置。"
            )
        if self.sink.value != self.sink_detail.kind:
            raise ValueError("runtime.logging.sink 必须与 sink_detail.kind 一致。")
        return self
