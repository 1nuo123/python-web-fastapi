"""
共享数据库会话管理器基础设施模块。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from src.infrastructure.persistence.sqlalchemy_session_factory import (
    SqlAlchemySessionFactory,
    SqlAlchemyUnitOfWork,
)


class SharedDbSessionManager:
    """
    共享数据库会话管理器，负责管理相关资源生命周期。
    """

    def __init__(self, session_factory: SqlAlchemySessionFactory) -> None:
        """
        初始化共享数据库会话管理器。

        :param session_factory: ``session_factory`` 工厂实例。约束：需符合 ``SqlAlchemySessionFactory`` 注解。
        :type session_factory: SqlAlchemySessionFactory
        :returns: 无返回值。
        :rtype: None
        """

        self._session_factory = session_factory

    def create_session(self) -> Session:
        """
        创建会话。

        :returns: 返回当前步骤新建的对象。
        :rtype: Session
        """

        return self._session_factory.create_session()

    def create_unit_of_work(self) -> SqlAlchemyUnitOfWork:
        """
        创建单元工作。

        :returns: 返回当前步骤新建的对象。
        :rtype: SqlAlchemyUnitOfWork
        """

        return self._session_factory.create_unit_of_work()

    def close(self) -> None:
        """
        处理关闭。

        :returns: 无返回值。
        :rtype: None
        """

        self._session_factory.dispose_engine()
