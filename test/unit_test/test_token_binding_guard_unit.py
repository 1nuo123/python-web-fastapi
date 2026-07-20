"""
Token-IP 绑定守卫单元测试模块。
"""

from __future__ import annotations

from src.infrastructure.cache.cache_key_builder import CacheKeyBuilder
from src.infrastructure.cache.memory_cache_store import MemoryCacheStore
from src.infrastructure.key_management.sensitive_digest_service import (
    SensitiveDigestService,
)
from src.infrastructure.security.token_binding_guard import TokenBindingGuard

TOKEN_VALUE = "token-value"
FIRST_IP = "127.0.0.1"
SECOND_IP = "127.0.0.2"


class TestTokenBindingGuardUnit:
    """
    Token-IP 绑定守卫单元测试集合。
    """

    def test_validate_when_ip_mismatch_should_return_false(self) -> None:
        """
        验证 IP 摘要不匹配时返回失败。
        """

        cache_store = MemoryCacheStore()
        guard = TokenBindingGuard(
            cache_store=cache_store,
            key_builder=CacheKeyBuilder(key_prefix="unit"),
            digest_service=SensitiveDigestService(salt="unit-test-secret"),
        )

        guard.bind(token=TOKEN_VALUE, ip=FIRST_IP, ttl_seconds=60)

        assert guard.validate(token=TOKEN_VALUE, ip=SECOND_IP) is False
        guard.clear(token=TOKEN_VALUE)
        assert guard.validate(token=TOKEN_VALUE, ip=SECOND_IP) is True
        cache_store.close()

    def test_validate_or_bind_should_create_binding_and_return_digests(self) -> None:
        """
        验证未绑定时写入摘要，异常 IP 时返回不匹配并可清理。
        """

        cache_store = MemoryCacheStore()
        guard = TokenBindingGuard(
            cache_store=cache_store,
            key_builder=CacheKeyBuilder(key_prefix="unit"),
            digest_service=SensitiveDigestService(salt="unit-test-secret"),
        )

        first_result = guard.validate_or_bind(
            token=TOKEN_VALUE,
            ip=FIRST_IP,
            ttl_seconds=60,
        )
        second_result = guard.validate_or_bind(
            token=TOKEN_VALUE,
            ip=SECOND_IP,
            ttl_seconds=60,
        )
        guard.clear(token=TOKEN_VALUE)
        cleared_result = guard.validate_or_bind(
            token=TOKEN_VALUE,
            ip=SECOND_IP,
            ttl_seconds=60,
        )

        assert first_result.matched is True
        assert first_result.binding_created is True
        assert second_result.matched is False
        assert second_result.token_digest == guard.build_token_digest(TOKEN_VALUE)
        assert cleared_result.matched is True
        cache_store.close()
