"""
密码哈希器基础设施模块。
"""

from __future__ import annotations

from passlib.context import CryptContext

from src.infrastructure.settings.application_settings import PasswordHashAlgorithm

ARGON2_HASH_SCHEME = PasswordHashAlgorithm.ARGON2.value


class PasswordHasher:
    """
    密码哈希器类型，用于封装当前模块中的相关行为或状态。
    """

    def __init__(self, algorithm: PasswordHashAlgorithm) -> None:
        """
        初始化密码哈希器。

        :param algorithm: 当前步骤使用的算法参数。约束：需符合 ``PasswordHashAlgorithm`` 注解。
        :type algorithm: PasswordHashAlgorithm
        :returns: 无返回值。
        :rtype: None
        """

        self._context = CryptContext(schemes=[algorithm.value], deprecated="auto")
        self._hash_scheme = algorithm

    def hash_password(self, password_plain: str) -> str:
        """
        处理哈希密码。

        :param password_plain: 明文密码，仅在当前调用链中短暂使用。约束：需符合 ``str`` 注解。
        :type password_plain: str
        :returns: 返回当前操作结果。
        :rtype: str
        """

        return self._context.hash(password_plain)

    def verify_password(self, password_plain: str, password_hash: str) -> bool:
        """
        处理校验密码。

        :param password_plain: 明文密码，仅在当前调用链中短暂使用。约束：需符合 ``str`` 注解。
        :type password_plain: str
        :param password_hash: 持久化的密码哈希值。约束：需符合 ``str`` 注解。
        :type password_hash: str
        :returns: 返回布尔判断结果。
        :rtype: bool
        """

        return self._context.verify(password_plain, password_hash)

    def needs_rehash(self, password_hash: str) -> bool:
        """
        处理需要重算哈希。

        :param password_hash: 持久化的密码哈希值。约束：需符合 ``str`` 注解。
        :type password_hash: str
        :returns: 返回布尔判断结果。
        :rtype: bool
        """

        return self._context.needs_update(password_hash)
