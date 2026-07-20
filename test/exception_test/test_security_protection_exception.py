"""
安全防护异常测试模块。
"""

from __future__ import annotations

import pytest
from starlette.requests import Request

from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.infrastructure.cache.cache_key_builder import CacheKeyBuilder
from src.infrastructure.key_management.sensitive_digest_service import SensitiveDigestService
from src.infrastructure.security.rate_limit_guard import RateLimitGuard


class FailingCacheStore:
    """
    总是失败的缓存存储。
    """

    def get_value(self, key: str) -> str | None:
        """
        读取缓存值。
        """

        raise RuntimeError("缓存故障")

    def set_value(self, key: str, value: str, ttl_seconds: int | None) -> None:
        """
        写入缓存值。
        """

        raise RuntimeError("缓存故障")

    def set_value_if_absent(
        self,
        key: str,
        value: str,
        ttl_seconds: int | None,
    ) -> bool:
        """
        条件写入缓存值。
        """

        raise RuntimeError("缓存故障")

    def increment_with_expire(self, key: str, ttl_seconds: int) -> int:
        """
        递增缓存值。
        """

        raise RuntimeError("缓存故障")

    def delete_value(self, key: str) -> None:
        """
        删除缓存值。
        """

        raise RuntimeError("缓存故障")

    def delete_value_if_equals(self, key: str, expected_value: str) -> bool:
        """
        条件删除缓存值。
        """

        raise RuntimeError("缓存故障")

    def compare_and_set_value(
        self,
        key: str,
        expected_value: str,
        next_value: str,
        ttl_seconds: int | None,
    ) -> bool:
        """
        条件替换缓存值。
        """

        raise RuntimeError("缓存故障")

    def refresh_value_if_equals(
        self,
        key: str,
        expected_value: str,
        ttl_seconds: int | None,
    ) -> bool:
        """
        条件刷新缓存值。
        """

        raise RuntimeError("缓存故障")

    def close(self) -> None:
        """
        关闭缓存。
        """


class TestSecurityProtectionException:
    """
    安全防护异常测试集合。
    """

    def test_rate_limit_when_cache_unavailable_should_fail_closed(self) -> None:
        """
        验证限流缓存不可用时 fail-closed。
        """

        guard = RateLimitGuard(
            cache_store=FailingCacheStore(),
            key_builder=CacheKeyBuilder(key_prefix="exception"),
            digest_service=SensitiveDigestService(salt="exception-test-secret"),
        )

        with pytest.raises(HttpFaultException):
            guard.evaluate(
                request=self._build_request(),
                limit=1,
                window_seconds=60,
            )

    def _build_request(self) -> Request:
        """
        构建请求。
        """

        return Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/health/live",
                "headers": [],
                "client": ("127.0.0.1", 12345),
                "scheme": "http",
                "server": ("testserver", 80),
            }
        )
