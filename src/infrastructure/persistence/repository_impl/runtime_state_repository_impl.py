"""
运行时状态仓储实现基础设施模块。
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.core.persistence_contract.repository_contract import Repository


class RuntimeStateRepositoryImpl(Repository):
    """
    运行时状态仓储实现，负责提供持久化访问逻辑。
    """

    def __init__(self, session: Session) -> None:
        """
        初始化运行时状态仓储实现。

        :param session: 当前数据库会话，生命周期由工作单元控制。约束：需符合 ``Session`` 注解。
        :type session: Session
        :returns: 无返回值。
        :rtype: None
        """

        self._session = session

    def ping(self) -> bool:
        """
        处理探活。

        :returns: 返回布尔判断结果。
        :rtype: bool
        """

        self._session.execute(text("SELECT 1"))
        return True
