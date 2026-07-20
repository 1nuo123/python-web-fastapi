"""离线测试 SQLite 引擎工厂。"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine

from src.infrastructure.persistence.sqlalchemy_engine_factory import (
    SqlAlchemyEngineFactory,
)
from src.infrastructure.persistence.sqlalchemy_metadata_registry import ORM_MODEL_METADATA
from src.infrastructure.settings.application_settings import DatabaseRuntimeSettings

SQLITE_FILE_DATABASE_URL_TEMPLATE = "sqlite+pysqlite:///{database_path}"
SQLITE_CHECK_SAME_THREAD_DISABLED = False
SQLITE_TEST_DATABASE_FILENAME = "offline-test.sqlite3"


class SqliteTestEngineFactory:
    """为单个测试应用延迟创建隔离的内存数据库。"""

    def __init__(self, database_url: str | None = None) -> None:
        """初始化离线测试引擎工厂。"""

        self._temporary_directory: TemporaryDirectory[str] | None = None
        self._database_url = database_url or self._build_temporary_database_url()
        self._engine: Engine | None = None
        self._validator = SqlAlchemyEngineFactory()

    def build(self, runtime_settings: DatabaseRuntimeSettings) -> Engine:
        """构建并初始化 SQLite 测试引擎。

        :param runtime_settings: 已完成校验的数据库配置，仅用于满足统一工厂边界。
        :type runtime_settings: DatabaseRuntimeSettings
        :returns: 已创建全部 ORM 表的内存数据库引擎。
        :rtype: Engine
        """

        _ = runtime_settings
        if self._engine is not None:
            return self._engine
        engine = self._create_engine()
        if self._temporary_directory is not None:
            event.listen(
                engine,
                "engine_disposed",
                self._cleanup_temporary_database,
                once=True,
            )
        ORM_MODEL_METADATA.create_all(bind=engine)
        self._engine = engine
        return engine

    def validate(self, engine: Engine) -> None:
        """验证 SQLite 测试引擎可连接。

        :param engine: 待验证测试引擎。
        :type engine: Engine
        :returns: 无返回值。
        :rtype: None
        """

        self._validator.validate(engine)

    @classmethod
    def build_file_database_url(cls, database_path: Path) -> str:
        """为需要验证重启语义的测试构建文件数据库 URL。"""

        return SQLITE_FILE_DATABASE_URL_TEMPLATE.format(
            database_path=database_path.resolve().as_posix()
        )

    def _create_engine(self) -> Engine:
        """按数据库 URL 构建隔离的 SQLite 引擎。"""

        connect_arguments = {
            "check_same_thread": SQLITE_CHECK_SAME_THREAD_DISABLED,
        }
        return create_engine(
            self._database_url,
            connect_args=connect_arguments,
        )

    def _build_temporary_database_url(self) -> str:
        """构建支持多连接隔离事务的临时文件数据库 URL。"""

        self._temporary_directory = TemporaryDirectory(ignore_cleanup_errors=True)
        return self.build_file_database_url(
            Path(self._temporary_directory.name) / SQLITE_TEST_DATABASE_FILENAME,
        )

    def _cleanup_temporary_database(self, _engine: Engine) -> None:
        """在引擎释放后删除临时数据库目录。"""

        if self._temporary_directory is None:
            return
        self._temporary_directory.cleanup()
        self._temporary_directory = None
