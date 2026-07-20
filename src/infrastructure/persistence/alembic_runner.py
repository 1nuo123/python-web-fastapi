"""
Alembic执行器基础设施模块。
"""

from __future__ import annotations

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config

from src.infrastructure.settings.application_settings import DatabaseRuntimeSettings

ALEMBIC_SCRIPT_LOCATION_OPTION = "script_location"
ALEMBIC_SQLALCHEMY_URL_OPTION = "sqlalchemy.url"
ALEMBIC_DATABASE_SCHEMA_OPTION = "app.database_schema"
ALEMBIC_CONNECT_TIMEOUT_OPTION = "app.connect_timeout_seconds"
ALEMBIC_TARGET_REVISION = "head"


class AlembicRunner:
    """
    Alembic执行器类型，用于封装当前模块中的相关行为或状态。
    """

    def __init__(
        self,
        logger: logging.Logger,
        script_location: str | Path | None = None,
    ) -> None:
        """
        初始化Alembic执行器。

        :param logger: 当前组件使用的日志记录器。
        :type logger: Any
        :param script_location: Alembic 脚本目录。默认值：`None`。约束：需符合 ``str | Path | None`` 注解。
        :type script_location: str | Path | None
        :returns: 无返回值。
        :rtype: None
        """

        self._logger = logger
        self._script_location = (
            Path(script_location)
            if script_location is not None
            else Path(__file__).resolve().parent / "alembic"
        )

    def upgrade_head(self, runtime_settings: DatabaseRuntimeSettings) -> None:
        """
        处理升级头部。

        :param runtime_settings: ``runtime_settings`` 配置对象。约束：需符合 ``DatabaseRuntimeSettings`` 注解。
        :type runtime_settings: DatabaseRuntimeSettings
        :returns: 无返回值。
        :rtype: None
        """

        alembic_config = Config()
        alembic_config.set_main_option(
            ALEMBIC_SCRIPT_LOCATION_OPTION,
            str(self._script_location),
        )
        alembic_config.set_main_option(
            ALEMBIC_SQLALCHEMY_URL_OPTION,
            runtime_settings.url,
        )
        alembic_config.set_main_option(
            ALEMBIC_DATABASE_SCHEMA_OPTION,
            runtime_settings.schema_name,
        )
        alembic_config.set_main_option(
            ALEMBIC_CONNECT_TIMEOUT_OPTION,
            str(runtime_settings.connect_timeout_seconds),
        )
        self._logger.info("开始执行数据库迁移。")
        command.upgrade(alembic_config, ALEMBIC_TARGET_REVISION)
        self._logger.info("数据库迁移执行完成。")
