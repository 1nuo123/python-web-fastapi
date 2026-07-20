"""SQLite 测试引擎工厂单元测试模块。"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect

from src.infrastructure.persistence.orm_model.auth_user_orm_model import AuthUserOrmModel
from src.infrastructure.settings.app_settings_loader import AppSettingsLoader
from src.infrastructure.settings.application_settings import AppEnvironment
from src.infrastructure.testing.sqlite_test_engine_factory import (
    SqliteTestEngineFactory,
)


class TestSqliteTestEngineFactoryUnit:
    """SQLite 测试引擎工厂单元测试集合。"""

    def test_build_when_offline_should_create_schema_and_release_engine(self) -> None:
        """验证离线引擎创建 ORM 表且可显式释放。"""

        settings = AppSettingsLoader().load_for_environment(AppEnvironment.TEST)
        factory = SqliteTestEngineFactory()
        engine = factory.build(settings.runtime.database)
        database_path: Path | None = None
        try:
            factory.validate(engine)
            database_name = engine.url.database
            if database_name is None:
                raise AssertionError("SQLite 测试数据库路径不能为空。")
            database_path = Path(database_name)

            assert inspect(engine).has_table(AuthUserOrmModel.__tablename__)
            assert database_path.is_file()
        finally:
            engine.dispose()
        assert database_path is not None
        assert not database_path.exists()
