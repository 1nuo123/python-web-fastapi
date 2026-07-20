"""
Redis 密钥环存储模块。
"""

from __future__ import annotations

from src.core.cache_contract.cache_namespace_contract import CacheNamespace
from src.core.cache_contract.cache_store_contract import CacheStore
from src.core.key_management_contract.key_ring_contract import KeyRingSnapshot
from src.infrastructure.cache.cache_key_builder import CacheKeyBuilder
from src.infrastructure.key_management.key_ring_store_contract import KeyRingStore

KEY_RING_CACHE_SEGMENT = "key_ring"
KEY_RING_CACHE_TTL_SECONDS: int | None = None


class RedisKeyRingStore(KeyRingStore):
    """
    Redis 密钥环存储。
    """

    def __init__(
        self,
        *,
        cache_store: CacheStore,
        key_builder: CacheKeyBuilder,
    ) -> None:
        """
        初始化密钥环存储。
        """

        self._cache_store = cache_store
        self._key_builder = key_builder

    def load_key_ring(self, key_family: str) -> KeyRingSnapshot | None:
        """
        读取密钥环。
        """

        raw_value = self._cache_store.get_value(self._build_key(key_family))
        if raw_value is None:
            return None
        return KeyRingSnapshot.model_validate_json(raw_value)

    def save_key_ring(self, snapshot: KeyRingSnapshot) -> None:
        """
        保存密钥环。
        """

        self._cache_store.set_value(
            self._build_key(snapshot.key_family),
            snapshot.model_dump_json(),
            KEY_RING_CACHE_TTL_SECONDS,
        )

    def save_key_ring_if_absent(self, snapshot: KeyRingSnapshot) -> bool:
        """
        当密钥环不存在时保存初始快照。

        :param snapshot: 待保存密钥环快照。
        :type snapshot: KeyRingSnapshot
        :returns: 保存成功返回 ``True``。
        :rtype: bool
        """

        return self._cache_store.set_value_if_absent(
            self._build_key(snapshot.key_family),
            snapshot.model_dump_json(),
            KEY_RING_CACHE_TTL_SECONDS,
        )

    def save_key_ring_if_version_matches(
        self,
        *,
        current_snapshot: KeyRingSnapshot,
        next_snapshot: KeyRingSnapshot,
    ) -> bool:
        """
        使用当前快照 JSON 作为版本执行 CAS 保存。

        :param current_snapshot: 调用方读取到的当前密钥环快照。
        :type current_snapshot: KeyRingSnapshot
        :param next_snapshot: 待保存的新密钥环快照。
        :type next_snapshot: KeyRingSnapshot
        :returns: 保存成功返回 ``True``。
        :rtype: bool
        """

        return self._cache_store.compare_and_set_value(
            self._build_key(current_snapshot.key_family),
            current_snapshot.model_dump_json(),
            next_snapshot.model_dump_json(),
            KEY_RING_CACHE_TTL_SECONDS,
        )

    def _build_key(self, key_family: str) -> str:
        """
        构建密钥环缓存键。
        """

        return self._key_builder.build(
            namespace=CacheNamespace.KEY_RING,
            key_parts=[KEY_RING_CACHE_SEGMENT, key_family],
        )
