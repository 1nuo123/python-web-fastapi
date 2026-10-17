"""
SQLAlchemy引擎工厂基础设施模块。
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TypedDict

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from src.core.exception_contract.error_code_catalog_contract import CoreErrorCode
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.infrastructure.settings.application_settings import DatabaseRuntimeSettings

DATABASE_HEALTHCHECK_SQL = "SELECT 1"
POSTGRES_SEARCH_PATH_TEMPLATE = "-csearch_path={schema}"


class PostgresqlConnectArguments(TypedDict):
    """
    PostgreSQL连接参数TypedDict 映射，用于描述结构化字典输入。

    :ivar connect_timeout: ``connect_timeout`` 字段。约束：需符合 ``int`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype connect_timeout: int
    :ivar options: ``options`` 字段。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype options: str
    """

    connect_timeout: int
    options: str


class SqlAlchemyEngineFactory:
    """
    SQLAlchemy引擎工厂，负责构建目标对象。
    """

    def build(self, runtime_settings: DatabaseRuntimeSettings) -> Engine:
        """
        处理构建。

        :param runtime_settings: ``runtime_settings`` 配置对象。约束：需符合 ``DatabaseRuntimeSettings`` 注解。
        :type runtime_settings: DatabaseRuntimeSettings
        :returns: 返回当前操作结果。
        :rtype: Engine
        """

        connect_arguments = PostgresqlConnectArguments(
            connect_timeout=runtime_settings.connect_timeout_seconds,
            options=(
                POSTGRES_SEARCH_PATH_TEMPLATE.format(schema=runtime_settings.schema_name)
                + f" -cstatement_timeout={runtime_settings.statement_timeout_seconds * 1000}"
                + f" -clock_timeout={runtime_settings.connect_timeout_seconds * 1000}"
            ),
        )
        return create_engine(
            runtime_settings.url,
            echo=runtime_settings.echo,
            future=True,
            pool_pre_ping=True,
            pool_size=runtime_settings.pool_size,
            max_overflow=runtime_settings.max_overflow,
            pool_recycle=runtime_settings.pool_recycle_seconds,
            pool_timeout=runtime_settings.connect_timeout_seconds,
            connect_args=connect_arguments,
        )

    def validate(self, engine: Engine) -> None:
        """
        处理校验。

        :param engine: SQLAlchemy 引擎实例。约束：需符合 ``Engine`` 注解。
        :type engine: Engine
        :returns: 无返回值。
        :rtype: None
        :raises HttpFaultException: 当业务校验失败、资源未就绪、配置错误或令牌状态异常时抛出。
        """

        try:
            with engine.connect() as connection:
                connection.execute(text(DATABASE_HEALTHCHECK_SQL))
        except SQLAlchemyError as exc:
            raise HttpFaultException(
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                error_code=CoreErrorCode.DATABASE_UNAVAILABLE,
                message="数据库连接不可用。",
                detail=str(exc),
            ) from exc
