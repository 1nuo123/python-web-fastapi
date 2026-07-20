"""
环境基础设施模块。
"""

from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from src.infrastructure.persistence import orm_model as _orm_model_registry
from src.infrastructure.persistence.sqlalchemy_metadata_registry import ORM_MODEL_METADATA

ALEMBIC_DATABASE_SCHEMA_OPTION = "app.database_schema"
ALEMBIC_CONNECT_TIMEOUT_OPTION = "app.connect_timeout_seconds"
ALEMBIC_SQLALCHEMY_URL_OPTION = "sqlalchemy.url"
OFFLINE_PARAMSTYLE = "named"
DEFAULT_CONNECT_TIMEOUT_SECONDS = 5
DEFAULT_DATABASE_SCHEMA = "public"
POSTGRES_SEARCH_PATH_TEMPLATE = "-csearch_path={schema}"
CREATE_SCHEMA_SQL_TEMPLATE = 'CREATE SCHEMA IF NOT EXISTS "{schema}"'


class AlembicEnvironment:
    """
    Alembic环境类型，用于封装当前模块中的相关行为或状态。
    """

    def __init__(self) -> None:
        """
        初始化Alembic环境。

        :returns: 无返回值。
        :rtype: None
        """

        self._config = context.config
        self._target_metadata = ORM_MODEL_METADATA
        database_url = self._config.get_main_option(ALEMBIC_SQLALCHEMY_URL_OPTION)
        if not database_url:
            raise RuntimeError("Alembic 缺少数据库连接地址。")
        self._database_url = database_url
        self._database_schema = self._config.get_main_option(
            ALEMBIC_DATABASE_SCHEMA_OPTION,
            DEFAULT_DATABASE_SCHEMA,
        )
        self._connect_timeout_seconds = int(
            self._config.get_main_option(
                ALEMBIC_CONNECT_TIMEOUT_OPTION,
                str(DEFAULT_CONNECT_TIMEOUT_SECONDS),
            )
        )
        self._orm_model_registry = _orm_model_registry

    def run(self) -> None:
        """
        运行当前流程。

        :returns: 无返回值。
        :rtype: None
        """

        if context.is_offline_mode():
            self._run_offline()
            return
        self._run_online()

    def _run_offline(self) -> None:
        """
        处理运行离线。

        :returns: 无返回值。
        :rtype: None
        """

        context.configure(
            url=self._database_url,
            target_metadata=self._target_metadata,
            literal_binds=True,
            dialect_opts={"paramstyle": OFFLINE_PARAMSTYLE},
            compare_type=True,
            compare_server_default=True,
            include_schemas=True,
            version_table_schema=self._database_schema,
        )
        with context.begin_transaction():
            context.run_migrations()

    def _run_online(self) -> None:
        """
        处理运行在线。

        :returns: 无返回值。
        :rtype: None
        """

        engine = create_engine(
            self._database_url,
            future=True,
            poolclass=NullPool,
            connect_args={
                "connect_timeout": self._connect_timeout_seconds,
                "options": POSTGRES_SEARCH_PATH_TEMPLATE.format(
                    schema=self._database_schema,
                ),
            },
        )
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        CREATE_SCHEMA_SQL_TEMPLATE.format(
                            schema=self._database_schema,
                        )
                    )
                )
            with engine.connect() as connection:
                context.configure(
                    connection=connection,
                    target_metadata=self._target_metadata,
                    compare_type=True,
                    compare_server_default=True,
                    include_schemas=True,
                    version_table_schema=self._database_schema,
                )
                with context.begin_transaction():
                    context.run_migrations()
        finally:
            engine.dispose()


AlembicEnvironment().run()
