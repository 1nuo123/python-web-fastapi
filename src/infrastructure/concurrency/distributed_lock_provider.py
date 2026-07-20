"""
分布式锁提供者基础设施模块。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from http import HTTPStatus

from src.core.cache_contract.cache_store_contract import CacheStore
from src.core.concurrency_contract.distributed_lock_contract import (
    DistributedLockLease,
    DistributedLockRequest,
)
from src.core.exception_contract.error_code_catalog_contract import CoreErrorCode
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.infrastructure.cache.cache_key_builder import CacheKeyBuilder
from src.infrastructure.concurrency.redis_distributed_lock_adapter import (
    RedisDistributedLockAdapter,
)

DISTRIBUTED_LOCK_UNAVAILABLE_MESSAGE = "分布式锁不可用。"
DISTRIBUTED_LOCK_BUSY_MESSAGE = "分布式锁获取失败。"
DISTRIBUTED_LOCK_DISABLED_MESSAGE = "分布式锁已禁用。"
DISTRIBUTED_LOCK_FAIL_CLOSED_POLICY = "fail_closed"


class DistributedLockProvider:
    """
    独立分布式锁提供者。
    """

    def __init__(
        self,
        *,
        cache_store: CacheStore,
        key_builder: CacheKeyBuilder,
        enabled: bool = True,
        adapter: RedisDistributedLockAdapter | None = None,
        timer: Callable[[], float] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        """
        初始化分布式锁提供者。

        :param cache_store: 缓存存储。
        :type cache_store: CacheStore
        :param key_builder: 缓存键构造器。
        :type key_builder: CacheKeyBuilder
        :param enabled: 是否启用锁能力。
        :type enabled: bool
        :param adapter: Redis 锁适配器。
        :type adapter: RedisDistributedLockAdapter | None
        :param timer: 单调时钟。
        :type timer: Callable[[], float] | None
        :param sleeper: 睡眠函数。
        :type sleeper: Callable[[float], None] | None
        :returns: 无返回值。
        :rtype: None
        """

        self._enabled = enabled
        self._timer = timer or time.monotonic
        self._sleeper = sleeper or time.sleep
        self._adapter = adapter or RedisDistributedLockAdapter(
            cache_store=cache_store,
            key_builder=key_builder,
        )

    def acquire(self, request: DistributedLockRequest) -> DistributedLockLease:
        """
        获取分布式锁。

        :param request: 分布式锁请求。
        :type request: DistributedLockRequest
        :returns: 分布式锁租约。
        :rtype: DistributedLockLease
        :raises HttpFaultException: 当锁不可用、被禁用或等待超时时抛出。
        """

        if not self._enabled:
            raise self._build_disabled_fault()
        try:
            lease = self._adapter.acquire(
                request=request,
                timer=self._timer,
                sleeper=self._sleeper,
            )
        except Exception as exc:
            raise self._build_unavailable_fault(exc) from exc
        if lease is not None:
            return lease
        raise HttpFaultException(
            status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            error_code=CoreErrorCode.CACHE_UNAVAILABLE,
            message=DISTRIBUTED_LOCK_BUSY_MESSAGE,
        )

    def release(self, lease: DistributedLockLease) -> DistributedLockLease:
        """
        释放分布式锁。

        :param lease: 分布式锁租约。
        :type lease: DistributedLockLease
        :returns: 标记释放状态后的租约。
        :rtype: DistributedLockLease
        """

        if not lease.acquired:
            return lease.model_copy(update={"released": False})
        try:
            released = self._adapter.release(lease)
        except Exception as exc:
            raise self._build_unavailable_fault(exc) from exc
        return lease.model_copy(update={"released": released})

    def refresh(self, lease: DistributedLockLease) -> DistributedLockLease:
        """
        刷新分布式锁租约。

        :param lease: 分布式锁租约。
        :type lease: DistributedLockLease
        :returns: 刷新后的租约。
        :rtype: DistributedLockLease
        """

        if not lease.acquired or lease.released:
            return lease.model_copy(update={"acquired": False})
        try:
            refreshed = self._adapter.refresh(lease)
        except Exception as exc:
            raise self._build_unavailable_fault(exc) from exc
        if not refreshed:
            return lease.model_copy(update={"acquired": False})
        return lease.model_copy(
            update={
                "acquired": True,
                "expires_at_epoch": self._adapter.calculate_expires_at_epoch(
                    lease_seconds=lease.lease_seconds,
                    timer=self._timer,
                ),
            }
        )

    def _build_unavailable_fault(self, exc: Exception) -> HttpFaultException:
        """
        构建分布式锁不可用异常。

        :param exc: 原始异常。
        :type exc: Exception
        :returns: HTTP 故障异常。
        :rtype: HttpFaultException
        """

        return HttpFaultException(
            status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            error_code=CoreErrorCode.CACHE_UNAVAILABLE,
            message=DISTRIBUTED_LOCK_UNAVAILABLE_MESSAGE,
            detail=str(exc),
        )

    def _build_disabled_fault(self) -> HttpFaultException:
        """
        构建分布式锁禁用异常。

        :returns: HTTP 故障异常。
        :rtype: HttpFaultException
        """

        return HttpFaultException(
            status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            error_code=CoreErrorCode.CACHE_UNAVAILABLE,
            message=DISTRIBUTED_LOCK_DISABLED_MESSAGE,
            detail=DISTRIBUTED_LOCK_FAIL_CLOSED_POLICY,
        )
