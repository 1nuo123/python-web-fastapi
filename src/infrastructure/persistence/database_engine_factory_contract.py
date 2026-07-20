"""数据库引擎工厂边界。"""

from __future__ import annotations

from typing import Protocol

from sqlalchemy.engine import Engine

from src.infrastructure.settings.application_settings import DatabaseRuntimeSettings


class DatabaseEngineFactory(Protocol):
    """声明运行时数据库引擎的构建与探活边界。"""

    def build(self, runtime_settings: DatabaseRuntimeSettings) -> Engine:
        """构建数据库引擎。

        :param runtime_settings: 数据库运行时配置。
        :type runtime_settings: DatabaseRuntimeSettings
        :returns: 数据库引擎。
        :rtype: Engine
        """

        ...

    def validate(self, engine: Engine) -> None:
        """验证数据库引擎可用性。

        :param engine: 待验证数据库引擎。
        :type engine: Engine
        :returns: 无返回值。
        :rtype: None
        """

        ...
