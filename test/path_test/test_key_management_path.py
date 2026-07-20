"""
密钥管理路径测试模块。
"""

from __future__ import annotations

from src.core.key_management_contract.key_management_contract import ManagedKeyFamilyEnvelope
from src.core.key_management_contract.key_rotation_policy_contract import (
    KeyRotationPolicyEnvelope,
)
from src.infrastructure.cache.cache_key_builder import CacheKeyBuilder
from src.infrastructure.cache.memory_cache_store import MemoryCacheStore
from src.infrastructure.concurrency.distributed_lock_provider import DistributedLockProvider
from src.infrastructure.key_management.key_management_service import KeyManagementService
from src.infrastructure.key_management.key_rotation_service import KeyRotationService
from src.infrastructure.key_management.redis_key_ring_store import RedisKeyRingStore


class TestKeyManagementPath:
    """
    密钥管理路径测试集合。
    """

    def test_key_family_initialize_and_read_current_key_should_follow_path(self) -> None:
        """
        验证密钥族初始化后可通过统一密钥管理服务读取当前密钥。
        """

        cache_store = MemoryCacheStore()
        key_builder = CacheKeyBuilder(key_prefix="path")
        service = KeyManagementService(
            key_ring_store=RedisKeyRingStore(cache_store=cache_store, key_builder=key_builder),
            key_rotation_service=KeyRotationService(),
            distributed_lock_provider=DistributedLockProvider(
                cache_store=cache_store,
                key_builder=key_builder,
            ),
        )
        service.initialize_key_family(self._build_key_family())

        current_key = service.get_current_key("jwt_signing")

        assert current_key.key_material != ""
        cache_store.close()

    def _build_key_family(self) -> ManagedKeyFamilyEnvelope:
        """
        构建密钥族。
        """

        return ManagedKeyFamilyEnvelope(
            family_name="jwt_signing",
            usage="jwt_signing",
            enabled=True,
            rotation_policy=KeyRotationPolicyEnvelope(
                enabled=True,
                rotation_interval_seconds=60,
                active_key_count=2,
            ),
        )
