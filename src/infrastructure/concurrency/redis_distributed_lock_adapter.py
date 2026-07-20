"""
Redis 分布式锁适配器模块。
"""

from __future__ import annotations

from collections.abc import Callable

from src.core.cache_contract.cache_namespace_contract import CacheNamespace
from src.core.cache_contract.cache_store_contract import CacheStore
from src.core.concurrency_contract.distributed_lock_contract import (
    DistributedLockLease,
    DistributedLockRequest,
)
from src.infrastructure.cache.cache_key_builder import CacheKeyBuilder

REDIS_LOCK_ADAPTER_RETRY_SLEEP_SECONDS = 0.05


class RedisDistributedLockAdapter:
    """
    Redis 锁适配器。

    该适配器把分布式锁 acquire/release/refresh 语义收口到 Redis 原子能力。
    当前项目通过 ``CacheStore`` 暴露 Redis 原子操作，后续替换专用 Redis 客户端时只需替换该适配器。
    """

    def __init__(self, *, cache_store: CacheStore, key_builder: CacheKeyBuilder) -> None:
        """
        初始化 Redis 锁适配器。

        :param cache_store: 缓存存储。
        :type cache_store: CacheStore
        :param key_builder: 缓存键构造器。
        :type key_builder: CacheKeyBuilder
        :returns: 无返回值。
        :rtype: None
        """

        self._cache_store = cache_store
        self._key_builder = key_builder

    def acquire(
        self,
        *,
        request: DistributedLockRequest,
        timer: Callable[[], float],
        sleeper: Callable[[float], None],
    ) -> DistributedLockLease | None:
        """
        获取 Redis 分布式锁。

        :param request: 锁获取请求。
        :type request: DistributedLockRequest
        :param timer: 单调时钟。
        :type timer: Callable[[], float]
        :param sleeper: 等待函数。
        :type sleeper: Callable[[float], None]
        :returns: 获取成功时返回租约；超时或未等待时返回 ``None``。
        :rtype: DistributedLockLease | None
        """

        lock_key = self.build_lock_key(request)
        deadline = timer() + request.wait_seconds
        while True:
            acquired = self._cache_store.set_value_if_absent(
                lock_key,
                request.owner,
                request.lease_seconds,
            )
            if acquired:
                return DistributedLockLease(
                    namespace=request.namespace,
                    key_digest=request.key_digest,
                    owner=request.owner,
                    lock_key=lock_key,
                    lease_seconds=request.lease_seconds,
                    expires_at_epoch=self.calculate_expires_at_epoch(
                        lease_seconds=request.lease_seconds,
                        timer=timer,
                    ),
                    acquired=True,
                )
            if request.wait_seconds == 0 or timer() >= deadline:
                return None
            sleeper(REDIS_LOCK_ADAPTER_RETRY_SLEEP_SECONDS)

    def release(self, lease: DistributedLockLease) -> bool:
        """
        按 owner 原子匹配释放锁。

        :param lease: 已获取的锁租约。
        :type lease: DistributedLockLease
        :returns: 返回是否实际释放。
        :rtype: bool
        """

        return self._cache_store.delete_value_if_equals(
            lease.lock_key,
            lease.owner,
        )

    def refresh(self, lease: DistributedLockLease) -> bool:
        """
        按 owner 原子匹配刷新锁 TTL。

        :param lease: 已获取的锁租约。
        :type lease: DistributedLockLease
        :returns: 返回是否实际刷新。
        :rtype: bool
        """

        return self._cache_store.refresh_value_if_equals(
            lease.lock_key,
            lease.owner,
            lease.lease_seconds,
        )

    def build_lock_key(self, request: DistributedLockRequest) -> str:
        """
        构建分布式锁缓存键。

        :param request: 锁获取请求。
        :type request: DistributedLockRequest
        :returns: 锁缓存键。
        :rtype: str
        """

        return self._key_builder.build(
            namespace=CacheNamespace.DISTRIBUTED_LOCK,
            key_parts=[request.namespace, request.key_digest],
        )

    def calculate_expires_at_epoch(
        self,
        *,
        lease_seconds: int,
        timer: Callable[[], float],
    ) -> int:
        """
        计算锁租约过期时间。

        :param lease_seconds: 租约秒数。
        :type lease_seconds: int
        :param timer: 单调时钟。
        :type timer: Callable[[], float]
        :returns: 过期时间戳。
        :rtype: int
        """

        return int(timer() + lease_seconds)
