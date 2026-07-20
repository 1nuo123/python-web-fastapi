"""
仓储契约核心契约模块。
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class Repository(ABC):
    """
    仓储抽象基类，定义持久化组件的基础探活能力。

    Repository 只负责持久化读写和依赖探活，不拥有事务边界。
    实现类禁止调用 ``commit()`` 或 ``rollback()``；无法处理的数据库异常必须继续向上抛出，
    由外层 ``UnitOfWork`` 调用方统一决定提交、回滚和资源释放。
    """

    @abstractmethod
    def ping(self) -> bool:
        """
        探测仓储依赖是否可用。

        :returns: 返回布尔判断结果；``True`` 表示仓储当前可用，``False`` 表示不可用。
        :rtype: bool
        """

        pass
