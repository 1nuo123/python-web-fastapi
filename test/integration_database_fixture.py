"""真实 PostgreSQL 集成测试夹具。"""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

import portalocker
import psycopg
import pytest
from psycopg import sql

from src.cli.run_database_migrations import (
    DATABASE_MIGRATION_EXIT_SUCCESS,
    DatabaseMigrationCli,
    MigrationJobStatus,
)
from src.infrastructure.settings.dotenv_settings_loader import DotenvSettingsLoader

TEST_APP_ENVIRONMENT = "test"
TEST_DATABASE_RESET_ENV_NAME = "TEST_DATABASE_RESET"
TEST_DATABASE_RESET_ENABLED = "1"
TEST_DATABASE_NAME_SUFFIX = "_test"
TEST_DATABASE_LOCK_DIRECTORY = Path(".tmp")
TEST_DATABASE_LOCK_FILE_NAME = "test_database_session.lock"
TEST_DATABASE_LOCK_TIMEOUT_SECONDS = 1800
TEST_DATABASE_LOCK_PATH = TEST_DATABASE_LOCK_DIRECTORY / TEST_DATABASE_LOCK_FILE_NAME
DEFAULT_POSTGRES_DATABASE_NAME = "fastapi_web_skeleton_dev"
DEFAULT_POSTGRES_PASSWORD = "local-dev-postgres-password"
DEFAULT_POSTGRES_HOST = "127.0.0.1"
DEFAULT_POSTGRES_PORT = "55432"
ROOT_DOTENV_PATH = Path(".env")
DATABASE_NAME_MISSING_MESSAGE = "DATABASE_URL 缺少数据库名称。"
DATABASE_RESET_REFUSED_MESSAGE = "测试数据库名称必须以 _test 结尾，拒绝执行重置。"
DATABASE_UNAVAILABLE_MESSAGE = "测试数据库不可访问。请启动 Docker PostgreSQL 并核对测试连接配置。"
DATABASE_MIGRATION_FAILURE_MESSAGE = "测试数据库迁移失败。"


@dataclass(frozen=True, slots=True)
class DatabaseResetPolicy:
    """测试数据库重置策略。"""

    reset_enabled: bool
    database_name: str

    def assert_allowed(self) -> None:
        """确认重置目标具有测试库后缀。"""

        if self.reset_enabled and not self.database_name.endswith(TEST_DATABASE_NAME_SUFFIX):
            raise RuntimeError(DATABASE_RESET_REFUSED_MESSAGE)


class IntegrationDatabaseHarness:
    """封装测试数据库创建、重置与迁移。"""

    @classmethod
    def build_database_url(cls) -> str:
        """从进程环境和根 dotenv 构建测试数据库地址。"""

        dotenv_values = (
            DotenvSettingsLoader()
            .load(
                dotenv_path=ROOT_DOTENV_PATH,
                environment=TEST_APP_ENVIRONMENT,
                enabled=True,
            )
            .variables
        )
        explicit_url = os.getenv("TEST_DATABASE_URL") or dotenv_values.get("TEST_DATABASE_URL")
        if explicit_url:
            return explicit_url
        host = os.getenv("POSTGRES_HOST", dotenv_values.get("POSTGRES_HOST", DEFAULT_POSTGRES_HOST))
        port = os.getenv(
            "POSTGRES_HOST_PORT",
            dotenv_values.get("POSTGRES_HOST_PORT", DEFAULT_POSTGRES_PORT),
        )
        user = os.getenv("POSTGRES_USER", dotenv_values.get("POSTGRES_USER", "postgres"))
        password = os.getenv(
            "POSTGRES_PASSWORD",
            dotenv_values.get("POSTGRES_PASSWORD", DEFAULT_POSTGRES_PASSWORD),
        )
        base_name = os.getenv(
            "POSTGRES_DB",
            dotenv_values.get("POSTGRES_DB", DEFAULT_POSTGRES_DATABASE_NAME),
        )
        database_name = os.getenv("POSTGRES_TEST_DB", f"{base_name}{TEST_DATABASE_NAME_SUFFIX}")
        return (
            "postgresql+psycopg://"
            f"{quote(user, safe='')}:{quote(password, safe='')}@{host}:{port}/{database_name}"
        )

    @staticmethod
    def to_psycopg_conninfo(sqlalchemy_url: str) -> str:
        """把 SQLAlchemy psycopg URL 转为 psycopg 连接串。"""

        prefix = "postgresql+psycopg://"
        if sqlalchemy_url.startswith(prefix):
            return f"postgresql://{sqlalchemy_url.removeprefix(prefix)}"
        return sqlalchemy_url

    @classmethod
    def ensure_database(cls, database_url: str) -> None:
        """安全创建或重置测试数据库。"""

        conninfo = cls.to_psycopg_conninfo(database_url)
        parts = urlsplit(conninfo)
        database_name = parts.path.lstrip("/")
        if not database_name:
            raise RuntimeError(DATABASE_NAME_MISSING_MESSAGE)
        reset_enabled = (
            os.getenv(
                TEST_DATABASE_RESET_ENV_NAME,
                TEST_DATABASE_RESET_ENABLED,
            )
            == TEST_DATABASE_RESET_ENABLED
        )
        policy = DatabaseResetPolicy(
            reset_enabled=reset_enabled,
            database_name=database_name,
        )
        policy.assert_allowed()
        maintenance_conninfo = urlunsplit(parts._replace(path="/postgres"))
        try:
            with psycopg.connect(maintenance_conninfo, autocommit=True) as connection:
                with connection.cursor() as cursor:
                    if reset_enabled:
                        cursor.execute(
                            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                                sql.Identifier(database_name)
                            )
                        )
                    cursor.execute(
                        "SELECT 1 FROM pg_database WHERE datname = %s",
                        (database_name,),
                    )
                    if cursor.fetchone() is None:
                        cursor.execute(
                            sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name))
                        )
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(DATABASE_UNAVAILABLE_MESSAGE) from exc


class IntegrationDatabaseFixtures:
    """提供显式真实数据库 fixture。"""

    @staticmethod
    def prepare() -> Iterator[str]:
        """串行准备测试库，执行迁移并释放跨进程锁。"""

        database_url = IntegrationDatabaseHarness.build_database_url()
        os.environ["DATABASE_URL"] = database_url
        TEST_DATABASE_LOCK_DIRECTORY.mkdir(exist_ok=True)
        with portalocker.Lock(
            str(TEST_DATABASE_LOCK_PATH),
            timeout=TEST_DATABASE_LOCK_TIMEOUT_SECONDS,
        ):
            IntegrationDatabaseHarness.ensure_database(database_url)
            result = DatabaseMigrationCli().execute()
            if (
                result.detail.status != MigrationJobStatus.SUCCESS
                or result.detail.exit_code != DATABASE_MIGRATION_EXIT_SUCCESS
            ):
                raise RuntimeError(DATABASE_MIGRATION_FAILURE_MESSAGE)
            yield database_url


integration_database = pytest.fixture(scope="session", autouse=False)(
    IntegrationDatabaseFixtures.prepare
)
