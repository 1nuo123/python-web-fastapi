"""
SQLAlchemy会话工厂基础设施模块。
"""

from __future__ import annotations

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from src.core.persistence_contract.unit_of_work_contract import PersistenceSession, UnitOfWork


class SqlAlchemyPersistenceSession(Session, PersistenceSession):
    """SQLAlchemy 持久化会话，落实核心层名义会话契约。"""


class SqlAlchemyUnitOfWork(UnitOfWork):
    """
    SQLAlchemy单元工作类型，用于封装当前模块中的相关行为或状态。
    """

    def __init__(self, session: SqlAlchemyPersistenceSession) -> None:
        """
        初始化SQLAlchemy单元工作。

        :param session: 当前数据库会话，生命周期由工作单元控制。约束：需符合 ``Session`` 注解。
        :type session: Session
        :returns: 无返回值。
        :rtype: None
        """

        self._session = session

    def get_session(self) -> SqlAlchemyPersistenceSession:
        """
        获取会话。

        :returns: 返回读取到的对象或状态快照。
        :rtype: Session
        """

        return self._session

    def commit(self) -> None:
        """
        处理提交。

        :returns: 无返回值。
        :rtype: None
        """

        self._session.commit()

    def flush(self) -> None:
        """
        处理刷新。

        :returns: 无返回值。
        :rtype: None
        """

        self._session.flush()

    def rollback(self) -> None:
        """
        处理回滚。

        :returns: 无返回值。
        :rtype: None
        """

        self._session.rollback()

    def dispose(self) -> None:
        """
        处理释放。

        :returns: 无返回值。
        :rtype: None
        """

        self._session.close()


class SqlAlchemySessionFactory:
    """
    SQLAlchemy会话工厂，负责构建目标对象。
    """

    def __init__(self, engine: Engine) -> None:
        """
        初始化SQLAlchemy会话工厂。

        :param engine: SQLAlchemy 引擎实例。约束：需符合 ``Engine`` 注解。
        :type engine: Engine
        :returns: 无返回值。
        :rtype: None
        """

        self._engine = engine
        self._factory = sessionmaker(
            bind=engine,
            class_=SqlAlchemyPersistenceSession,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
            future=True,
        )

    def create_session(self) -> SqlAlchemyPersistenceSession:
        """
        创建会话。

        :returns: 返回当前步骤新建的对象。
        :rtype: Session
        """

        return self._factory()

    def create_unit_of_work(self) -> SqlAlchemyUnitOfWork:
        """
        创建单元工作。

        :returns: 返回当前步骤新建的对象。
        :rtype: SqlAlchemyUnitOfWork
        """

        return SqlAlchemyUnitOfWork(self.create_session())

    def dispose_engine(self) -> None:
        """
        处理释放引擎。

        :returns: 无返回值。
        :rtype: None
        """

        self._engine.dispose()
