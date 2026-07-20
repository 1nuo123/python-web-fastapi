"""
分布式锁 Redis 集成测试模块。
"""

from __future__ import annotations

import os
import time

import pytest

from src.core.concurrency_contract.distributed_lock_contract import DistributedLockRequest
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.infrastructure.cache.cache_key_builder import CacheKeyBuilder
from src.infrastructure.cache.redis_cache_store import RedisCacheStore
from src.infrastructure.concurrency.distributed_lock_provider import (
    DistributedLockProvider,
)
from test.redis_integration_support import RedisIntegrationAvailability

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.usefixtures("integration_database"),
    pytest.mark.redis,
]


REDIS_URL_ENV_NAME = "REDIS_URL"
DEFAULT_REDIS_URL = "redis://127.0.0.1:56379/0"
REDIS_UNAVAILABLE_URL = "redis://127.0.0.1:1/0"
REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS = 1
LOCK_DIGEST = "1234567890abcdef"
LOCK_OWNER = "owner-1"
SECOND_LOCK_OWNER = "owner-2"
LOCK_SLEEP_SECONDS = 1.2


class TestDistributedLockRedisIntegration:
    """
    分布式锁 Redis 集成测试集合。
    """

    def test_lock_should_use_redis_owner_ttl_refresh_and_fail_closed(self) -> None:
        """
        验证 Redis SET NX EX、owner 防误删、TTL 过期、原子续租和不可用失败关闭。
        """

        redis_url = os.getenv(REDIS_URL_ENV_NAME, DEFAULT_REDIS_URL)
        RedisIntegrationAvailability.fail_when_unavailable(
            redis_url=redis_url,
            timeout_seconds=REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS,
        )
        cache_store = RedisCacheStore(redis_url)
        provider = DistributedLockProvider(
            cache_store=cache_store,
            key_builder=CacheKeyBuilder(key_prefix="integration_lock"),
        )
        request = self._build_request(owner=LOCK_OWNER, lease_seconds=1)
        second_request = self._build_request(owner=SECOND_LOCK_OWNER, lease_seconds=1)
        lease = provider.acquire(request)
        try:
            wrong_owner_lease = lease.model_copy(update={"owner": SECOND_LOCK_OWNER})
            wrong_release = provider.release(wrong_owner_lease)
            with pytest.raises(HttpFaultException):
                provider.acquire(second_request)
            refreshed_lease = provider.refresh(lease)
            time.sleep(LOCK_SLEEP_SECONDS)
            next_lease = provider.acquire(second_request)
            unavailable_provider = DistributedLockProvider(
                cache_store=RedisCacheStore(
                    REDIS_UNAVAILABLE_URL,
                    socket_connect_timeout_seconds=REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS,
                ),
                key_builder=CacheKeyBuilder(key_prefix="integration_lock"),
            )

            assert wrong_release.released is False
            assert refreshed_lease.acquired is True
            assert next_lease.acquired is True
            with pytest.raises(HttpFaultException):
                unavailable_provider.acquire(request)
        finally:
            cache_store.delete_value(lease.lock_key)
            cache_store.close()

    def _build_request(
        self,
        *,
        owner: str,
        lease_seconds: int,
    ) -> DistributedLockRequest:
        """
        构建锁请求。
        """

        return DistributedLockRequest(
            namespace="integration",
            key_digest=LOCK_DIGEST,
            owner=owner,
            lease_seconds=lease_seconds,
            wait_seconds=0,
        )
