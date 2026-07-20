"""
分布式锁提供者单元测试模块。
"""

from __future__ import annotations

import pytest

from src.core.concurrency_contract.distributed_lock_contract import DistributedLockRequest
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.infrastructure.cache.cache_key_builder import CacheKeyBuilder
from src.infrastructure.cache.memory_cache_store import MemoryCacheStore
from src.infrastructure.concurrency.distributed_lock_provider import (
    DISTRIBUTED_LOCK_FAIL_CLOSED_POLICY,
    DistributedLockProvider,
)
from src.infrastructure.testing.fake_cache_store import UnavailableCacheStore

LOCK_DIGEST = "1234567890abcdef"
LOCK_OWNER = "owner-1"
SECOND_LOCK_OWNER = "owner-2"


class TestDistributedLockProviderUnit:
    """
    分布式锁提供者单元测试集合。
    """

    def test_acquire_same_key_should_only_allow_one_owner(self) -> None:
        """
        验证同一锁键只能被一个 owner 获取。
        """

        cache_store = MemoryCacheStore()
        provider = DistributedLockProvider(
            cache_store=cache_store,
            key_builder=CacheKeyBuilder(key_prefix="unit"),
        )
        request = self._build_request(LOCK_OWNER)
        lease = provider.acquire(request)

        with pytest.raises(HttpFaultException):
            provider.acquire(self._build_request(SECOND_LOCK_OWNER))
        released_lease = provider.release(lease)
        second_lease = provider.acquire(self._build_request(SECOND_LOCK_OWNER))

        assert released_lease.released is True
        assert second_lease.acquired is True
        cache_store.close()

    def test_release_when_owner_not_match_should_not_delete_lock(self) -> None:
        """
        验证非 owner 释放不影响原锁。
        """

        cache_store = MemoryCacheStore()
        provider = DistributedLockProvider(
            cache_store=cache_store,
            key_builder=CacheKeyBuilder(key_prefix="unit"),
        )
        lease = provider.acquire(self._build_request(LOCK_OWNER))
        wrong_owner_lease = lease.model_copy(update={"owner": SECOND_LOCK_OWNER})

        released_lease = provider.release(wrong_owner_lease)

        assert released_lease.released is False
        with pytest.raises(HttpFaultException):
            provider.acquire(self._build_request(SECOND_LOCK_OWNER))
        cache_store.close()

    def test_refresh_should_extend_owner_lease_and_reject_wrong_owner(self) -> None:
        """
        验证锁续租会延长 owner 租约且非 owner 无法续租。
        """

        current_time = 1000.0
        cache_store = MemoryCacheStore(timer=lambda: current_time)
        provider = DistributedLockProvider(
            cache_store=cache_store,
            key_builder=CacheKeyBuilder(key_prefix="unit"),
            timer=lambda: current_time,
        )
        lease = provider.acquire(self._build_request(LOCK_OWNER))
        current_time = 1003.0

        refreshed_lease = provider.refresh(lease)
        wrong_owner_lease = refreshed_lease.model_copy(update={"owner": SECOND_LOCK_OWNER})
        rejected_lease = provider.refresh(wrong_owner_lease)
        current_time = 1007.0
        still_busy = False
        try:
            provider.acquire(self._build_request(SECOND_LOCK_OWNER))
        except HttpFaultException:
            still_busy = True

        assert refreshed_lease.acquired is True
        assert refreshed_lease.expires_at_epoch == 1008
        assert rejected_lease.acquired is False
        assert still_busy is True
        cache_store.close()

    def test_lease_expiry_and_unavailable_cache_should_fail_closed(self) -> None:
        """
        验证租约过期后可重新获取，缓存不可用时失败关闭。
        """

        current_time = 1000.0
        cache_store = MemoryCacheStore(timer=lambda: current_time)
        provider = DistributedLockProvider(
            cache_store=cache_store,
            key_builder=CacheKeyBuilder(key_prefix="unit"),
            timer=lambda: current_time,
        )
        provider.acquire(self._build_request(LOCK_OWNER))
        current_time = 1006.0

        next_lease = provider.acquire(self._build_request(SECOND_LOCK_OWNER))

        assert next_lease.acquired is True
        cache_store.close()

        unavailable_provider = DistributedLockProvider(
            cache_store=UnavailableCacheStore(),
            key_builder=CacheKeyBuilder(key_prefix="unit"),
        )
        with pytest.raises(HttpFaultException):
            unavailable_provider.acquire(self._build_request(LOCK_OWNER))

    def test_disabled_provider_should_report_fixed_fail_closed_policy(self) -> None:
        """
        验证锁禁用时返回固定 fail-closed 策略。
        """

        cache_store = MemoryCacheStore()
        provider = DistributedLockProvider(
            cache_store=cache_store,
            key_builder=CacheKeyBuilder(key_prefix="unit"),
            enabled=False,
        )

        with pytest.raises(HttpFaultException) as exc_info:
            provider.acquire(self._build_request(LOCK_OWNER))

        assert exc_info.value.detail == DISTRIBUTED_LOCK_FAIL_CLOSED_POLICY
        cache_store.close()

    def _build_request(self, owner: str) -> DistributedLockRequest:
        """
        构建锁请求。
        """

        return DistributedLockRequest(
            namespace="unit",
            key_digest=LOCK_DIGEST,
            owner=owner,
            lease_seconds=5,
            wait_seconds=0,
        )
