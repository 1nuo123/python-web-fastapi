"""
Token-IP 绑定守卫模块。
"""

from __future__ import annotations

from dataclasses import dataclass

from src.core.cache_contract.cache_namespace_contract import CacheNamespace
from src.core.cache_contract.cache_store_contract import CacheStore
from src.infrastructure.cache.cache_key_builder import CacheKeyBuilder
from src.infrastructure.key_management.sensitive_digest_service import SensitiveDigestService

TOKEN_BINDING_CACHE_SEGMENT = "token_ip"


@dataclass(slots=True)
class TokenBindingValidationResult:
    """
    Token-IP 绑定校验结果。
    """

    matched: bool
    binding_created: bool
    token_digest: str
    ip_digest: str


class TokenBindingGuard:
    """
    Token-IP 绑定守卫。
    """

    def __init__(
        self,
        *,
        cache_store: CacheStore,
        key_builder: CacheKeyBuilder,
        digest_service: SensitiveDigestService,
    ) -> None:
        """
        初始化 Token-IP 绑定守卫。
        """

        self._cache_store = cache_store
        self._key_builder = key_builder
        self._digest_service = digest_service

    def build_token_digest(self, token: str) -> str:
        """
        构建 token 摘要。
        """

        return self._digest_service.digest(token)

    def build_ip_digest(self, ip: str) -> str:
        """
        构建 IP 摘要。
        """

        return self._digest_service.digest(ip)

    def bind(self, *, token: str, ip: str, ttl_seconds: int) -> None:
        """
        绑定 token 摘要与 IP 摘要。
        """

        self._cache_store.set_value(
            self._build_key_by_digest(self.build_token_digest(token)),
            self.build_ip_digest(ip),
            ttl_seconds,
        )

    def validate(self, *, token: str, ip: str) -> bool:
        """
        校验 token 摘要与 IP 摘要是否匹配。
        """

        cached_ip_digest = self._cache_store.get_value(
            self._build_key_by_digest(self.build_token_digest(token))
        )
        if cached_ip_digest is None:
            return True
        return cached_ip_digest == self.build_ip_digest(ip)

    def validate_or_bind(
        self,
        *,
        token: str,
        ip: str,
        ttl_seconds: int,
    ) -> TokenBindingValidationResult:
        """
        校验绑定；未绑定时写入当前 token 与 IP 摘要。
        """

        token_digest = self.build_token_digest(token)
        ip_digest = self.build_ip_digest(ip)
        cached_ip_digest = self._cache_store.get_value(self._build_key_by_digest(token_digest))
        if cached_ip_digest is None:
            self._cache_store.set_value(
                self._build_key_by_digest(token_digest),
                ip_digest,
                ttl_seconds,
            )
            return TokenBindingValidationResult(
                matched=True,
                binding_created=True,
                token_digest=token_digest,
                ip_digest=ip_digest,
            )
        return TokenBindingValidationResult(
            matched=cached_ip_digest == ip_digest,
            binding_created=False,
            token_digest=token_digest,
            ip_digest=ip_digest,
        )

    def clear(self, *, token: str) -> None:
        """
        清理 token 绑定。
        """

        self._cache_store.delete_value(self._build_key_by_digest(self.build_token_digest(token)))

    def _build_key_by_digest(self, token_digest: str) -> str:
        """
        构建绑定缓存键。
        """

        return self._key_builder.build(
            namespace=CacheNamespace.TOKEN_BINDING,
            key_parts=[TOKEN_BINDING_CACHE_SEGMENT, token_digest],
        )
