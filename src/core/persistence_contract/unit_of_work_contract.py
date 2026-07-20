"""
单元工作契约核心契约模块。
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class PersistenceSession(ABC):
    """
    持久化会话协议，隔离核心契约对具体 ORM 会话类型的依赖。

    该类型是跨层传递事务会话的名义标记。核心层不暴露具体 ORM 方法；基础设施
    实现必须提供其专用子类，事务提交、回滚和释放仍统一由 ``UnitOfWork`` 承担。
    """


class UnitOfWork(ABC):
    """
    单元工作抽象基类，定义事务边界与会话生命周期控制能力。

    ``UnitOfWork`` 是持久化链路唯一事务边界，负责 ``commit()``、``rollback()``、
    ``flush()`` 与 ``dispose()``。Repository 只能复用当前工作单元暴露的会话执行读写，
    不得自行提交、回滚或释放事务资源。
    """

    @abstractmethod
    def get_session(self) -> PersistenceSession:
        """
        读取当前事务会话。

        :returns: 返回当前事务绑定的持久化会话协议对象。
        :rtype: PersistenceSession
        """

        pass

    @abstractmethod
    def commit(self) -> None:
        """
        提交当前事务。

        :returns: 无返回值。
        :rtype: None
        """

        pass

    @abstractmethod
    def flush(self) -> None:
        """
        刷新当前事务中的待写入状态。

        :returns: 无返回值。
        :rtype: None
        """

        pass

    @abstractmethod
    def rollback(self) -> None:
        """
        回滚当前事务。

        :returns: 无返回值。
        :rtype: None
        """

        pass

    @abstractmethod
    def dispose(self) -> None:
        """
        释放当前事务关联资源。

        :returns: 无返回值。
        :rtype: None
        """

        pass
