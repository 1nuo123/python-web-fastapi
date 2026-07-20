"""
缓存键构建器基础设施模块。
"""

from __future__ import annotations

from src.core.cache_contract.cache_namespace_contract import (
    CACHE_KEY_SEGMENT_SEPARATOR,
    CacheNamespace,
)

CACHE_KEY_SEGMENT_MINIMUM_LENGTH = 1


class CacheKeyBuilder:
    """
    缓存键构建器类型，用于封装当前模块中的相关行为或状态。
    """

    def __init__(self, *, key_prefix: str) -> None:
        """
        初始化缓存键构建器。

        :param key_prefix: 缓存键统一前缀。约束：需符合 ``str`` 注解。
        :type key_prefix: str
        :returns: 无返回值。
        :rtype: None
        """

        self._key_prefix = key_prefix.strip()
        self._assert_segment_not_empty(self._key_prefix, "runtime.cache.key_prefix")
        self._assert_segment_without_separator(
            self._key_prefix,
            "runtime.cache.key_prefix",
        )

    def build(self, *, namespace: CacheNamespace, key_parts: list[str]) -> str:
        """
        处理构建。

        :param namespace: 缓存命名空间，用于隔离同类键。约束：需符合 ``CacheNamespace`` 注解。
        :type namespace: CacheNamespace
        :param key_parts: 缓存键片段列表，按顺序拼接为最终键。约束：需符合 ``list[str]`` 注解。
        :type key_parts: list[str]
        :returns: 返回当前操作结果。
        :rtype: str
        """

        normalized_parts = [self._normalize_segment(part) for part in key_parts]
        return CACHE_KEY_SEGMENT_SEPARATOR.join(
            [self._key_prefix, namespace.value, *normalized_parts]
        )

    def _normalize_segment(self, segment: str) -> str:
        """
        规范化片段。

        :param segment: 缓存键单个片段。约束：需符合 ``str`` 注解。
        :type segment: str
        :returns: 返回当前操作结果。
        :rtype: str
        """

        normalized_segment = segment.strip()
        self._assert_segment_not_empty(normalized_segment, "缓存键片段")
        self._assert_segment_without_separator(normalized_segment, "缓存键片段")
        return normalized_segment

    def _assert_segment_not_empty(self, segment: str, field_name: str) -> None:
        """
        断言片段不空值。

        :param segment: 缓存键单个片段。约束：需符合 ``str`` 注解。
        :type segment: str
        :param field_name: 字段名称。约束：需符合 ``str`` 注解。
        :type field_name: str
        :returns: 无返回值。
        :rtype: None
        :raises ValueError: 当输入值或配置值不满足当前实现约束时抛出。
        """

        if len(segment) < CACHE_KEY_SEGMENT_MINIMUM_LENGTH:
            raise ValueError(f"{field_name} 不能为空。")

    def _assert_segment_without_separator(self, segment: str, field_name: str) -> None:
        """
        断言片段不包含缓存键分隔符。

        :param segment: 缓存键单个片段。约束：需符合 ``str`` 注解。
        :type segment: str
        :param field_name: 字段名称。约束：需符合 ``str`` 注解。
        :type field_name: str
        :returns: 无返回值。
        :rtype: None
        :raises ValueError: 当输入值或配置值不满足当前实现约束时抛出。
        """

        if CACHE_KEY_SEGMENT_SEPARATOR in segment:
            raise ValueError(f"{field_name} 不能包含缓存键分隔符。")
