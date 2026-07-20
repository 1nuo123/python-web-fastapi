"""
内存缓存存储基础设施模块。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from threading import RLock

from cachetools import TLRUCache

from src.core.cache_contract.cache_store_contract import CacheStore

MEMORY_CACHE_ENTRY_MINIMUM_TTL_SECONDS = 1
MEMORY_CACHE_MAX_ENTRIES_MINIMUM = 1
MEMORY_CACHE_COUNTER_INITIAL_VALUE = 1
MEMORY_CACHE_COUNTER_INCREMENT_STEP = 1
DEFAULT_MEMORY_CACHE_MAX_ENTRIES = 1024


@dataclass(slots=True)
class MemoryCacheEntry:
    """
    内存缓存入口数据对象，用于承载当前流程的结构化字段。

    :ivar value: 缓存值或业务值。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype value: str
    :ivar ttl_seconds: 缓存 TTL 秒数；空值表示不过期。
    :vartype ttl_seconds: int | None
    """

    value: str
    ttl_seconds: int | None


class MemoryCacheStore(CacheStore):
    """
    内存缓存存储实现，负责保存和读取状态。
    """

    def __init__(
        self,
        timer: Callable[[], float] | None = None,
        *,
        max_entries: int = DEFAULT_MEMORY_CACHE_MAX_ENTRIES,
    ) -> None:
        """
        初始化内存缓存存储。

        :param timer: 计时器或时钟实现。默认值：`None`。约束：需符合 ``Callable[[], float] | None`` 注解。
        :type timer: Callable[[], float] | None
        :param max_entries: 内存缓存允许保存的最大条目数。默认值：`DEFAULT_MEMORY_CACHE_MAX_ENTRIES`。约束：需符合 ``int`` 注解。
        :type max_entries: int
        :returns: 无返回值。
        :rtype: None
        :raises ValueError: 当输入值或配置值不满足当前实现约束时抛出。
        """

        if max_entries < MEMORY_CACHE_MAX_ENTRIES_MINIMUM:
            raise ValueError("内存缓存最大条目数必须大于 0。")
        self._timer = timer or time.monotonic
        self._lock = RLock()
        self._items: TLRUCache[str, MemoryCacheEntry] = TLRUCache(
            maxsize=max_entries,
            timer=self._timer,
            ttu=self._calculate_expire_at,
        )

    def get_value(self, key: str) -> str | None:
        """
        获取值。

        :param key: 缓存键。约束：需符合 ``str`` 注解。
        :type key: str
        :returns: 返回读取到的对象或状态快照。
        :rtype: str | None
        """

        with self._lock:
            entry = self._items.get(key)
            return None if entry is None else entry.value

    def set_value(self, key: str, value: str, ttl_seconds: int | None) -> None:
        """
        设置值。

        :param key: 缓存键。约束：需符合 ``str`` 注解。
        :type key: str
        :param value: 当前流程要写入或比较的值。约束：需符合 ``str`` 注解。
        :type value: str
        :param ttl_seconds: 缓存 TTL 秒数；传入 ``None`` 时表示不过期。
        :type ttl_seconds: int | None
        :returns: 无返回值。
        :rtype: None
        :raises ValueError: 当输入值或配置值不满足当前实现约束时抛出。
        """

        if ttl_seconds is not None and ttl_seconds < MEMORY_CACHE_ENTRY_MINIMUM_TTL_SECONDS:
            raise ValueError("缓存 TTL 必须大于 0。")
        with self._lock:
            self._items[key] = MemoryCacheEntry(
                value=value,
                ttl_seconds=ttl_seconds,
            )

    def set_value_if_absent(self, key: str, value: str, ttl_seconds: int | None) -> bool:
        """
        当缓存键不存在时写入值。

        :param key: 缓存键。
        :type key: str
        :param value: 当前流程要写入的值。
        :type value: str
        :param ttl_seconds: 缓存 TTL 秒数。
        :type ttl_seconds: int | None
        :returns: 写入成功返回 ``True``。
        :rtype: bool
        """

        if ttl_seconds is not None and ttl_seconds < MEMORY_CACHE_ENTRY_MINIMUM_TTL_SECONDS:
            raise ValueError("缓存 TTL 必须大于 0。")
        with self._lock:
            if key in self._items:
                return False
            self._items[key] = MemoryCacheEntry(
                value=value,
                ttl_seconds=ttl_seconds,
            )
            return True

    def delete_value_if_equals(self, key: str, expected_value: str) -> bool:
        """
        当缓存值匹配时删除键。

        :param key: 缓存键。
        :type key: str
        :param expected_value: 预期值。
        :type expected_value: str
        :returns: 删除成功返回 ``True``。
        :rtype: bool
        """

        with self._lock:
            entry = self._items.get(key)
            if entry is None or entry.value != expected_value:
                return False
            self._items.pop(key, None)
            return True

    def compare_and_set_value(
        self,
        key: str,
        expected_value: str,
        next_value: str,
        ttl_seconds: int | None,
    ) -> bool:
        """
        当缓存值匹配时原子替换为新值。

        :param key: 缓存键。
        :type key: str
        :param expected_value: 预期值。
        :type expected_value: str
        :param next_value: 新值。
        :type next_value: str
        :param ttl_seconds: 缓存 TTL 秒数。
        :type ttl_seconds: int | None
        :returns: 替换成功返回 ``True``。
        :rtype: bool
        """

        if ttl_seconds is not None and ttl_seconds < MEMORY_CACHE_ENTRY_MINIMUM_TTL_SECONDS:
            raise ValueError("缓存 TTL 必须大于 0。")
        with self._lock:
            entry = self._items.get(key)
            if entry is None or entry.value != expected_value:
                return False
            self._items[key] = MemoryCacheEntry(
                value=next_value,
                ttl_seconds=ttl_seconds,
            )
            return True

    def refresh_value_if_equals(
        self,
        key: str,
        expected_value: str,
        ttl_seconds: int | None,
    ) -> bool:
        """
        当缓存值匹配时刷新 TTL。

        :param key: 缓存键。
        :type key: str
        :param expected_value: 预期值。
        :type expected_value: str
        :param ttl_seconds: 缓存 TTL 秒数。
        :type ttl_seconds: int | None
        :returns: 刷新成功返回 ``True``。
        :rtype: bool
        """

        if ttl_seconds is not None and ttl_seconds < MEMORY_CACHE_ENTRY_MINIMUM_TTL_SECONDS:
            raise ValueError("缓存 TTL 必须大于 0。")
        with self._lock:
            entry = self._items.get(key)
            if entry is None or entry.value != expected_value:
                return False
            self._items[key] = MemoryCacheEntry(
                value=expected_value,
                ttl_seconds=ttl_seconds,
            )
            return True

    def increment_with_expire(self, key: str, ttl_seconds: int) -> int:
        """
        原子递增内存缓存计数并保持固定窗口过期语义。

        当键首次创建时写入 TTL；当键已存在且仍未过期时，只更新计数值，不重新插入
        ``TLRUCache``，避免刷新原过期时间。

        :param key: 缓存键。约束：需符合 ``str`` 注解。
        :type key: str
        :param ttl_seconds: 缓存 TTL 秒数。约束：需符合 ``int`` 注解。
        :type ttl_seconds: int
        :returns: 递增后的计数值。
        :rtype: int
        :raises ValueError: 当 TTL 非正数时抛出。
        """

        if ttl_seconds < MEMORY_CACHE_ENTRY_MINIMUM_TTL_SECONDS:
            raise ValueError("缓存 TTL 必须大于 0。")
        with self._lock:
            entry = self._items.get(key)
            if entry is None:
                self._items[key] = MemoryCacheEntry(
                    value=str(MEMORY_CACHE_COUNTER_INITIAL_VALUE),
                    ttl_seconds=ttl_seconds,
                )
                return MEMORY_CACHE_COUNTER_INITIAL_VALUE
            next_value = int(entry.value) + MEMORY_CACHE_COUNTER_INCREMENT_STEP
            entry.value = str(next_value)
            return next_value

    def delete_value(self, key: str) -> None:
        """
        删除值。

        :param key: 缓存键。约束：需符合 ``str`` 注解。
        :type key: str
        :returns: 无返回值。
        :rtype: None
        """

        with self._lock:
            self._items.pop(key, None)

    def close(self) -> None:
        """
        处理关闭。

        :returns: 无返回值。
        :rtype: None
        """

        with self._lock:
            self._items.clear()

    def _calculate_expire_at(
        self,
        _key: str,
        entry: MemoryCacheEntry,
        current_time: float,
    ) -> float:
        """
        计算过期在。

        :param _key: 当前步骤使用的键参数。约束：需符合 ``str`` 注解。
        :type _key: str
        :param entry: 当前步骤使用的入口参数。约束：需符合 ``MemoryCacheEntry`` 注解。
        :type entry: MemoryCacheEntry
        :param current_time: 当前步骤使用的当前time参数。约束：需符合 ``float`` 注解。
        :type current_time: float
        :returns: 返回当前操作结果。
        :rtype: float
        """

        if entry.ttl_seconds is None:
            return float("inf")
        return current_time + entry.ttl_seconds
