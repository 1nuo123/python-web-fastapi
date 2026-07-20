"""
风险信号守卫模块。
"""

from __future__ import annotations

from dataclasses import dataclass

from src.core.cache_contract.cache_namespace_contract import CacheNamespace
from src.core.cache_contract.cache_store_contract import CacheStore
from src.infrastructure.cache.cache_key_builder import CacheKeyBuilder
from src.infrastructure.key_management.sensitive_digest_service import (
    SensitiveDigestService,
)

RISK_SIGNAL_AUTH_FAILURE_SEGMENT = "auth_failure"
RISK_SIGNAL_USERNAME_SEGMENT = "username"
RISK_SIGNAL_IP_SEGMENT = "ip"
RISK_SIGNAL_USERNAME_IP_SEGMENT = "username_ip"
RISK_SIGNAL_REQUEST_SEGMENT = "request"
RISK_SIGNAL_PATH_SEGMENT = "path"


@dataclass(slots=True)
class AuthRiskSignalResult:
    """
    认证风险信号结果。
    """

    username_failure_count: int
    ip_failure_count: int
    username_ip_failure_count: int
    password_spray_suspected: bool


class RiskSignalGuard:
    """
    风险信号守卫。
    """

    def __init__(
        self,
        *,
        cache_store: CacheStore,
        key_builder: CacheKeyBuilder,
        digest_service: SensitiveDigestService,
    ) -> None:
        """
        初始化风险信号守卫。
        """

        self._cache_store = cache_store
        self._key_builder = key_builder
        self._digest_service = digest_service

    def record_auth_failure(
        self,
        *,
        username: str,
        ip: str,
        window_seconds: int,
        password_spray_limit: int,
    ) -> AuthRiskSignalResult:
        """
        记录认证失败并输出轻量风险信号。
        """

        username_digest = self._digest_service.digest(username)
        ip_digest = self._digest_service.digest(ip)
        username_failure_count = self._increment_counter(
            [RISK_SIGNAL_USERNAME_SEGMENT, username_digest],
            window_seconds,
        )
        ip_failure_count = self._increment_counter(
            [RISK_SIGNAL_IP_SEGMENT, ip_digest],
            window_seconds,
        )
        username_ip_failure_count = self._increment_counter(
            [RISK_SIGNAL_USERNAME_IP_SEGMENT, username_digest, ip_digest],
            window_seconds,
        )
        return AuthRiskSignalResult(
            username_failure_count=username_failure_count,
            ip_failure_count=ip_failure_count,
            username_ip_failure_count=username_ip_failure_count,
            password_spray_suspected=ip_failure_count >= password_spray_limit,
        )

    def record_request_observation(
        self,
        *,
        path: str,
        ip: str,
        window_seconds: int,
    ) -> int:
        """
        记录请求级风险信号。
        """

        ip_digest = self._digest_service.digest(ip)
        path_digest = self._digest_service.digest(path)
        return self._increment_counter(
            [
                RISK_SIGNAL_REQUEST_SEGMENT,
                RISK_SIGNAL_PATH_SEGMENT,
                path_digest,
                ip_digest,
            ],
            window_seconds,
        )

    def _increment_counter(self, key_parts: list[str], window_seconds: int) -> int:
        """
        递增风险信号计数器。
        """

        cache_key = self._key_builder.build(
            namespace=CacheNamespace.RISK_SIGNAL,
            key_parts=[RISK_SIGNAL_AUTH_FAILURE_SEGMENT, *key_parts],
        )
        return self._cache_store.increment_with_expire(cache_key, window_seconds)
