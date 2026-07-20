"""
Alembic 环境单元测试模块。
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import sqlalchemy

ALEMBIC_ENV_PATH = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "infrastructure"
    / "persistence"
    / "alembic"
    / "env.py"
)
ALEMBIC_TEST_MODULE_NAME = "test_alembic_environment_runtime"
ALEMBIC_CONTEXT_MODULE_NAME = "alembic"
ALEMBIC_DATABASE_URL = "postgresql+psycopg://user:password@localhost:5432/app"
ALEMBIC_DATABASE_SCHEMA = "unit_schema"
ALEMBIC_CONNECT_TIMEOUT = "5"
SQLALCHEMY_URL_OPTION = "sqlalchemy.url"
DATABASE_SCHEMA_OPTION = "app.database_schema"
CONNECT_TIMEOUT_OPTION = "app.connect_timeout_seconds"
EXPECTED_DISPOSE_COUNT = 1
EXPECTED_RUN_MIGRATIONS_COUNT = 1


class FakeAlembicConfig:
    """
    Alembic 配置测试替身。
    """

    def get_main_option(self, key: str, default: str | None = None) -> str:
        """
        读取 Alembic 主配置项。
        """

        values = {
            SQLALCHEMY_URL_OPTION: ALEMBIC_DATABASE_URL,
            DATABASE_SCHEMA_OPTION: ALEMBIC_DATABASE_SCHEMA,
            CONNECT_TIMEOUT_OPTION: ALEMBIC_CONNECT_TIMEOUT,
        }
        return values.get(key, default or "")


@dataclass(slots=True)
class FakeTransactionContext:
    """
    Alembic 事务上下文测试替身。
    """

    def __enter__(self) -> FakeTransactionContext:
        """
        进入事务上下文。
        """

        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> bool:
        """
        退出事务上下文。
        """

        _ = exc_type
        _ = exc_value
        _ = traceback
        return False


@dataclass(slots=True)
class FakeConnectionContext:
    """
    SQLAlchemy 连接上下文测试替身。
    """

    executed_statements: list[str]

    def __enter__(self) -> FakeConnectionContext:
        """
        进入连接上下文。
        """

        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> bool:
        """
        退出连接上下文。
        """

        _ = exc_type
        _ = exc_value
        _ = traceback
        return False

    def execute(self, statement: object) -> None:
        """
        记录执行的 SQL 语句。
        """

        self.executed_statements.append(str(statement))


class FakeEngine:
    """
    SQLAlchemy engine 测试替身。
    """

    def __init__(self) -> None:
        """
        初始化 engine 测试替身。
        """

        self.dispose_count = 0
        self.executed_statements: list[str] = []

    def begin(self) -> FakeConnectionContext:
        """
        创建事务连接上下文。
        """

        return FakeConnectionContext(self.executed_statements)

    def connect(self) -> FakeConnectionContext:
        """
        创建普通连接上下文。
        """

        return FakeConnectionContext(self.executed_statements)

    def dispose(self) -> None:
        """
        释放 engine 资源。
        """

        self.dispose_count += 1


class FakeAlembicContext:
    """
    Alembic context 测试替身。
    """

    def __init__(self, *, raise_on_migration: bool = False) -> None:
        """
        初始化 Alembic context 测试替身。
        """

        self.config = FakeAlembicConfig()
        self.raise_on_migration = raise_on_migration
        self.configure_calls: list[dict[str, Any]] = []
        self.run_migrations_count = 0

    def is_offline_mode(self) -> bool:
        """
        返回在线迁移模式。
        """

        return False

    def configure(self, **kwargs: Any) -> None:
        """
        记录 Alembic configure 调用。
        """

        self.configure_calls.append(kwargs)

    def begin_transaction(self) -> FakeTransactionContext:
        """
        创建迁移事务上下文。
        """

        return FakeTransactionContext()

    def run_migrations(self) -> None:
        """
        执行迁移或抛出测试异常。
        """

        self.run_migrations_count += 1
        if self.raise_on_migration:
            raise RuntimeError("模拟迁移失败。")


@dataclass(frozen=True, slots=True)
class AlembicLoadResult:
    """
    Alembic 环境加载结果。
    """

    context: FakeAlembicContext
    engine: FakeEngine


class TestAlembicEnvironmentUnit:
    """
    Alembic 环境单元测试集合。
    """

    def test_online_run_should_dispose_engine_after_success(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        验证在线迁移成功后释放 engine。
        """

        result = self._load_alembic_env(monkeypatch=monkeypatch)

        assert result.engine.dispose_count == EXPECTED_DISPOSE_COUNT
        assert result.context.run_migrations_count == EXPECTED_RUN_MIGRATIONS_COUNT

    def test_online_run_should_dispose_engine_after_failure(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        验证在线迁移失败后仍释放 engine。
        """

        runtime = self._build_alembic_runtime(raise_on_migration=True)

        with pytest.raises(RuntimeError):
            self._load_alembic_env(monkeypatch=monkeypatch, runtime=runtime)

        assert runtime.engine.dispose_count == EXPECTED_DISPOSE_COUNT

    def _load_alembic_env(
        self,
        *,
        monkeypatch: pytest.MonkeyPatch,
        runtime: AlembicLoadResult | None = None,
    ) -> AlembicLoadResult:
        """
        使用测试替身加载 Alembic env.py。
        """

        load_runtime = runtime or self._build_alembic_runtime()
        fake_context = load_runtime.context
        fake_alembic_module = ModuleType(ALEMBIC_CONTEXT_MODULE_NAME)
        fake_alembic_module.context = fake_context
        fake_engine = load_runtime.engine

        def fake_create_engine(*args: object, **kwargs: object) -> FakeEngine:
            """
            返回测试 engine。
            """

            _ = args
            _ = kwargs
            return fake_engine

        monkeypatch.setitem(
            sys.modules,
            ALEMBIC_CONTEXT_MODULE_NAME,
            fake_alembic_module,
        )
        monkeypatch.setattr(sqlalchemy, "create_engine", fake_create_engine)
        sys.modules.pop(ALEMBIC_TEST_MODULE_NAME, None)
        spec = importlib.util.spec_from_file_location(
            ALEMBIC_TEST_MODULE_NAME,
            ALEMBIC_ENV_PATH,
        )
        if spec is None or spec.loader is None:
            raise AssertionError("Alembic env.py 加载规格缺失。")
        module = importlib.util.module_from_spec(spec)
        try:
            sys.modules[ALEMBIC_TEST_MODULE_NAME] = module
            spec.loader.exec_module(module)
        finally:
            sys.modules.pop(ALEMBIC_TEST_MODULE_NAME, None)
        return load_runtime

    def _build_alembic_runtime(
        self,
        *,
        raise_on_migration: bool = False,
    ) -> AlembicLoadResult:
        """
        构建 Alembic 加载测试运行时。
        """

        return AlembicLoadResult(
            context=FakeAlembicContext(raise_on_migration=raise_on_migration),
            engine=FakeEngine(),
        )
