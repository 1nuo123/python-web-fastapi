"""
缓存存储契约核心契约模块。
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class CacheStore(ABC):
    """
    缓存存储抽象基类，定义底层缓存读写能力。
    """

    @abstractmethod
    def get_value(self, key: str) -> str | None:
        """
        读取缓存值。

        :param key: 缓存键。约束：需符合 ``str`` 注解。
        :type key: str
        :returns: 返回缓存中当前键对应的原始字符串值；未命中时返回 ``None``。
        :rtype: str | None
        """

        pass

    @abstractmethod
    def set_value(self, key: str, value: str, ttl_seconds: int | None) -> None:
        """
        写入缓存值。

        :param key: 缓存键。约束：需符合 ``str`` 注解。
        :type key: str
        :param value: 待写入的原始字符串值。约束：需符合 ``str`` 注解。
        :type value: str
        :param ttl_seconds: 缓存 TTL 秒数；``None`` 表示不过期。
        :type ttl_seconds: int | None
        :returns: 无返回值。
        :rtype: None
        """

        pass

    @abstractmethod
    def set_value_if_absent(
        self,
        key: str,
        value: str,
        ttl_seconds: int | None,
    ) -> bool:
        """
        当缓存键不存在时写入值。

        :param key: 缓存键。约束：需符合 ``str`` 注解。
        :type key: str
        :param value: 待写入的原始字符串值。约束：需符合 ``str`` 注解。
        :type value: str
        :param ttl_seconds: 缓存 TTL 秒数；``None`` 表示不过期。
        :type ttl_seconds: int | None
        :returns: 写入成功返回 ``True``，键已存在返回 ``False``。
        :rtype: bool
        """

        pass

    @abstractmethod
    def compare_and_set_value(
        self,
        key: str,
        expected_value: str,
        next_value: str,
        ttl_seconds: int | None,
    ) -> bool:
        """
        当缓存值与预期值一致时原子替换为新值。

        :param key: 缓存键。约束：需符合 ``str`` 注解。
        :type key: str
        :param expected_value: 预期原始字符串值。约束：需符合 ``str`` 注解。
        :type expected_value: str
        :param next_value: 待写入原始字符串值。约束：需符合 ``str`` 注解。
        :type next_value: str
        :param ttl_seconds: 缓存 TTL 秒数；``None`` 表示不过期。
        :type ttl_seconds: int | None
        :returns: 替换成功返回 ``True``。
        :rtype: bool
        """

        pass

    @abstractmethod
    def delete_value_if_equals(self, key: str, expected_value: str) -> bool:
        """
        当缓存值与预期值一致时删除键。

        :param key: 缓存键。约束：需符合 ``str`` 注解。
        :type key: str
        :param expected_value: 预期值。约束：需符合 ``str`` 注解。
        :type expected_value: str
        :returns: 删除成功返回 ``True``。
        :rtype: bool
        """

        pass

    @abstractmethod
    def refresh_value_if_equals(
        self,
        key: str,
        expected_value: str,
        ttl_seconds: int | None,
    ) -> bool:
        """
        当缓存值与预期值一致时刷新 TTL。

        :param key: 缓存键。约束：需符合 ``str`` 注解。
        :type key: str
        :param expected_value: 预期值。约束：需符合 ``str`` 注解。
        :type expected_value: str
        :param ttl_seconds: 缓存 TTL 秒数；``None`` 表示不过期。
        :type ttl_seconds: int | None
        :returns: 刷新成功返回 ``True``。
        :rtype: bool
        """

        pass

    @abstractmethod
    def increment_with_expire(self, key: str, ttl_seconds: int) -> int:
        """
        原子递增缓存计数并确保固定窗口过期时间。

        当键首次创建时必须设置 ``ttl_seconds`` 对应的过期时间；当键已存在且仍未过期时，
        只递增计数值，不得刷新或延长原有过期窗口。

        :param key: 缓存键。约束：需符合 ``str`` 注解。
        :type key: str
        :param ttl_seconds: 缓存 TTL 秒数。约束：需符合 ``int`` 注解，并由调用方保证大于 0。
        :type ttl_seconds: int
        :returns: 递增后的计数值。
        :rtype: int
        """

        pass

    @abstractmethod
    def delete_value(self, key: str) -> None:
        """
        删除缓存值。

        :param key: 缓存键。约束：需符合 ``str`` 注解。
        :type key: str
        :returns: 无返回值。
        :rtype: None
        """

        pass

    @abstractmethod
    def close(self) -> None:
        """
        关闭底层缓存资源。

        :returns: 无返回值。
        :rtype: None
        """

        pass
