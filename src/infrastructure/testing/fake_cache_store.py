"""
模拟缓存存储基础设施模块。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from http import HTTPStatus

from src.core.cache_contract.cache_store_contract import CacheStore
from src.core.exception_contract.error_code_catalog_contract import CoreErrorCode
from src.core.exception_contract.http_fault_contract import HttpFaultException

FAKE_CACHE_TTL_MINIMUM_SECONDS = 1
FAKE_CACHE_COUNTER_INITIAL_VALUE = 1
FAKE_CACHE_COUNTER_INCREMENT_STEP = 1
UNAVAILABLE_CACHE_MESSAGE = "测试缓存不可用。"
UNAVAILABLE_CACHE_DETAIL = "测试缓存后端不可达。"


@dataclass(slots=True)
class FakeCacheEntry:
    """
    模拟缓存入口数据对象，用于承载当前流程的结构化字段。

    :ivar value: 缓存值或业务值。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype value: str
    :ivar expires_at_epoch: ``expires_at_epoch`` 字段。约束：需符合 ``float`` 注解。默认值：无，必须显式提供。取值语义：用于表达 Unix 时间戳秒值。
    :vartype expires_at_epoch: float
    """

    value: str
    expires_at_epoch: float


class FakeCacheStore(CacheStore):
    """
    模拟缓存存储实现，负责保存和读取状态。
    """

    def __init__(self, timer: Callable[[], float] | None = None) -> None:
        """
        初始化模拟缓存存储。

        :param timer: 计时器或时钟实现。默认值：`None`。约束：需符合 ``Callable[[], float] | None`` 注解。
        :type timer: Callable[[], float] | None
        :returns: 无返回值。
        :rtype: None
        """

        self._timer = timer or time.monotonic
        self._items: dict[str, FakeCacheEntry] = {}

    def get_value(self, key: str) -> str | None:
        """
        获取值。

        :param key: 缓存键。约束：需符合 ``str`` 注解。
        :type key: str
        :returns: 返回读取到的对象或状态快照。
        :rtype: str | None
        """

        entry = self._items.get(key)
        if entry is None:
            return None
        if self._timer() >= entry.expires_at_epoch:
            self._items.pop(key, None)
            return None
        return entry.value

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

        if ttl_seconds is not None and ttl_seconds < FAKE_CACHE_TTL_MINIMUM_SECONDS:
            raise ValueError("缓存 TTL 必须大于 0。")
        expires_at_epoch = float("inf") if ttl_seconds is None else self._timer() + ttl_seconds
        self._items[key] = FakeCacheEntry(
            value=value,
            expires_at_epoch=expires_at_epoch,
        )

    def set_value_if_absent(self, key: str, value: str, ttl_seconds: int | None) -> bool:
        """
        当键不存在时写入缓存值。
        """

        if self.get_value(key) is not None:
            return False
        self.set_value(key, value, ttl_seconds)
        return True

    def increment_with_expire(self, key: str, ttl_seconds: int) -> int:
        """
        原子递增模拟缓存计数并保持固定窗口过期语义。

        :param key: 缓存键。
        :type key: str
        :param ttl_seconds: 缓存 TTL 秒数。
        :type ttl_seconds: int
        :returns: 递增后的计数值。
        :rtype: int
        """

        if ttl_seconds < FAKE_CACHE_TTL_MINIMUM_SECONDS:
            raise ValueError("缓存 TTL 必须大于 0。")
        current_value = self.get_value(key)
        if current_value is None:
            self.set_value(key, str(FAKE_CACHE_COUNTER_INITIAL_VALUE), ttl_seconds)
            return FAKE_CACHE_COUNTER_INITIAL_VALUE
        next_value = int(current_value) + FAKE_CACHE_COUNTER_INCREMENT_STEP
        entry = self._items[key]
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

        self._items.pop(key, None)

    def delete_value_if_equals(self, key: str, expected_value: str) -> bool:
        """
        当缓存值等于预期值时删除键。
        """

        if self.get_value(key) != expected_value:
            return False
        self.delete_value(key)
        return True

    def compare_and_set_value(
        self,
        key: str,
        expected_value: str,
        next_value: str,
        ttl_seconds: int | None,
    ) -> bool:
        """
        当缓存值等于预期值时替换键。
        """

        if self.get_value(key) != expected_value:
            return False
        self.set_value(key, next_value, ttl_seconds)
        return True

    def refresh_value_if_equals(
        self,
        key: str,
        expected_value: str,
        ttl_seconds: int | None,
    ) -> bool:
        """
        当缓存值等于预期值时刷新 TTL。
        """

        if self.get_value(key) != expected_value:
            return False
        self.set_value(key, expected_value, ttl_seconds)
        return True

    def close(self) -> None:
        """
        处理关闭。

        :returns: 无返回值。
        :rtype: None
        """

        self._items.clear()


class UnavailableCacheStore(CacheStore):
    """
    不可用缓存存储测试替身，用于模拟 Redis 不可用异常。
    """

    def get_value(self, key: str) -> str | None:
        """
        获取值并始终抛出缓存不可用异常。

        :param key: 缓存键。约束：需符合 ``str`` 注解。
        :type key: str
        :returns: 不返回正常结果。
        :rtype: str | None
        :raises HttpFaultException: 始终抛出缓存不可用异常。
        """

        _ = key
        raise self._build_cache_unavailable_exception()

    def set_value(self, key: str, value: str, ttl_seconds: int | None) -> None:
        """
        设置值并始终抛出缓存不可用异常。

        :param key: 缓存键。约束：需符合 ``str`` 注解。
        :type key: str
        :param value: 当前流程要写入或比较的值。约束：需符合 ``str`` 注解。
        :type value: str
        :param ttl_seconds: 缓存 TTL 秒数。约束：需符合 ``int`` 注解。
        :type ttl_seconds: int | None
        :returns: 无返回值。
        :rtype: None
        :raises HttpFaultException: 始终抛出缓存不可用异常。
        """

        _ = key
        _ = value
        _ = ttl_seconds
        raise self._build_cache_unavailable_exception()

    def set_value_if_absent(self, key: str, value: str, ttl_seconds: int | None) -> bool:
        """
        条件写入并始终抛出缓存不可用异常。
        """

        _ = key
        _ = value
        _ = ttl_seconds
        raise self._build_cache_unavailable_exception()

    def increment_with_expire(self, key: str, ttl_seconds: int) -> int:
        """
        递增计数并始终抛出缓存不可用异常。

        :param key: 缓存键。
        :type key: str
        :param ttl_seconds: 缓存 TTL 秒数。
        :type ttl_seconds: int
        :returns: 不返回正常结果。
        :rtype: int
        :raises HttpFaultException: 始终抛出缓存不可用异常。
        """

        _ = key
        _ = ttl_seconds
        raise self._build_cache_unavailable_exception()

    def delete_value(self, key: str) -> None:
        """
        删除值并始终抛出缓存不可用异常。

        :param key: 缓存键。约束：需符合 ``str`` 注解。
        :type key: str
        :returns: 无返回值。
        :rtype: None
        :raises HttpFaultException: 始终抛出缓存不可用异常。
        """

        _ = key
        raise self._build_cache_unavailable_exception()

    def delete_value_if_equals(self, key: str, expected_value: str) -> bool:
        """
        条件删除并始终抛出缓存不可用异常。
        """

        _ = key
        _ = expected_value
        raise self._build_cache_unavailable_exception()

    def compare_and_set_value(
        self,
        key: str,
        expected_value: str,
        next_value: str,
        ttl_seconds: int | None,
    ) -> bool:
        """
        条件替换并始终抛出缓存不可用异常。
        """

        _ = key
        _ = expected_value
        _ = next_value
        _ = ttl_seconds
        raise self._build_cache_unavailable_exception()

    def refresh_value_if_equals(
        self,
        key: str,
        expected_value: str,
        ttl_seconds: int | None,
    ) -> bool:
        """
        条件续租并始终抛出缓存不可用异常。
        """

        _ = key
        _ = expected_value
        _ = ttl_seconds
        raise self._build_cache_unavailable_exception()

    def close(self) -> None:
        """
        关闭测试替身资源。

        :returns: 无返回值。
        :rtype: None
        """

    def _build_cache_unavailable_exception(self) -> HttpFaultException:
        """
        构建缓存不可用异常。

        :returns: 返回缓存不可用 HTTP 故障异常。
        :rtype: HttpFaultException
        """

        return HttpFaultException(
            status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            error_code=CoreErrorCode.CACHE_UNAVAILABLE,
            message=UNAVAILABLE_CACHE_MESSAGE,
            detail=UNAVAILABLE_CACHE_DETAIL,
        )
