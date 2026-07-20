"""
密钥管理 Redis 集成测试模块。
"""

from __future__ import annotations

import os

import pytest

from src.core.cache_contract.cache_namespace_contract import CacheNamespace
from src.core.key_management_contract.key_management_contract import (
    ManagedKeyFamilyEnvelope,
)
from src.core.key_management_contract.key_rotation_policy_contract import (
    KeyRotationPolicyEnvelope,
)
from src.infrastructure.cache.cache_key_builder import CacheKeyBuilder
from src.infrastructure.cache.redis_cache_store import RedisCacheStore
from src.infrastructure.concurrency.distributed_lock_provider import (
    DistributedLockProvider,
)
from src.infrastructure.key_management.key_management_service import KeyManagementService
from src.infrastructure.key_management.key_rotation_service import KeyRotationService
from src.infrastructure.key_management.redis_key_ring_store import (
    KEY_RING_CACHE_SEGMENT,
    RedisKeyRingStore,
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
REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS = 1
KEY_FAMILY_NAME = "jwt_signing_integration"


class TestKeyManagementRedisIntegration:
    """
    密钥管理 Redis 集成测试集合。
    """

    def test_key_management_should_initialize_rotate_and_read_old_key(self) -> None:
        """
        验证 Redis 密钥环初始化、幂等读取、轮转和旧 key 兼容窗口。
        """

        current_time = 1000.0
        redis_url = os.getenv(REDIS_URL_ENV_NAME, DEFAULT_REDIS_URL)
        RedisIntegrationAvailability.fail_when_unavailable(
            redis_url=redis_url,
            timeout_seconds=REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS,
        )
        cache_store = RedisCacheStore(
            redis_url,
            socket_connect_timeout_seconds=REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS,
        )
        key_builder = CacheKeyBuilder(key_prefix="integration_key")
        key_ring_key = key_builder.build(
            namespace=CacheNamespace.KEY_RING,
            key_parts=[KEY_RING_CACHE_SEGMENT, KEY_FAMILY_NAME],
        )
        cache_store.delete_value(key_ring_key)
        service = KeyManagementService(
            key_ring_store=RedisKeyRingStore(
                cache_store=cache_store,
                key_builder=key_builder,
            ),
            key_rotation_service=KeyRotationService(timer=lambda: current_time),
            distributed_lock_provider=DistributedLockProvider(
                cache_store=cache_store,
                key_builder=key_builder,
                timer=lambda: current_time,
            ),
        )
        key_family = self._build_key_family()
        try:
            first_snapshot = service.initialize_key_family(key_family)
            second_snapshot = service.initialize_key_family(key_family)
            current_time = 1011.0
            rotated_snapshot = service.rotate_key_family_if_due(key_family)
            previous_key = service.get_key_by_id(
                KEY_FAMILY_NAME,
                first_snapshot.current_key_id,
            )

            assert first_snapshot.current_key_id == second_snapshot.current_key_id
            assert rotated_snapshot.current_key_id != first_snapshot.current_key_id
            assert previous_key.key_id == first_snapshot.current_key_id
        finally:
            cache_store.delete_value(key_ring_key)
            cache_store.close()

    def _build_key_family(self) -> ManagedKeyFamilyEnvelope:
        """
        构建密钥族。
        """

        return ManagedKeyFamilyEnvelope(
            family_name=KEY_FAMILY_NAME,
            usage="jwt_signing",
            enabled=True,
            rotation_policy=KeyRotationPolicyEnvelope(
                enabled=True,
                rotation_interval_seconds=10,
                active_key_count=2,
                compatibility_window_seconds=30,
            ),
        )
