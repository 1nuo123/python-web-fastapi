"""数据库方言公共定义。"""

from __future__ import annotations

from enum import StrEnum


class DatabaseDialect(StrEnum):
    """声明当前持久化边界支持的数据库方言。"""

    POSTGRESQL = "postgresql"
    SQLITE = "sqlite"
