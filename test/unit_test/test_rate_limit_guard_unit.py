"""
限流守卫单元测试模块。
"""

from __future__ import annotations

from starlette.requests import Request

from src.core.http_contract.request_scope_contract import RequestScope
from src.core.security_contract.rate_limit_policy_contract import RateLimitKeyDimension
from src.infrastructure.cache.cache_key_builder import CacheKeyBuilder
from src.infrastructure.cache.memory_cache_store import MemoryCacheStore
from src.infrastructure.key_management.sensitive_digest_service import (
    SensitiveDigestService,
)
from src.infrastructure.security.rate_limit_guard import RateLimitGuard


class TestRateLimitGuardUnit:
    """
    限流守卫单元测试集合。
    """

    def test_evaluate_when_count_exceeds_limit_should_return_exceeded(self) -> None:
        """
        验证超过阈值后返回超限结果。
        """

        cache_store = MemoryCacheStore()
        guard = RateLimitGuard(
            cache_store=cache_store,
            key_builder=CacheKeyBuilder(key_prefix="unit"),
            digest_service=SensitiveDigestService(salt="unit-test-secret"),
        )
        request = self._build_request()

        first_result = guard.evaluate(request=request, limit=1, window_seconds=60)
        second_result = guard.evaluate(request=request, limit=1, window_seconds=60)

        assert first_result.exceeded is False
        assert second_result.exceeded is True
        cache_store.close()

    def test_evaluate_should_isolate_subject_path_method_and_auth_field(self) -> None:
        """
        验证 subject、path+method 和认证字段摘要参与限流键。
        """

        cache_store = MemoryCacheStore()
        guard = RateLimitGuard(
            cache_store=cache_store,
            key_builder=CacheKeyBuilder(key_prefix="unit"),
            digest_service=SensitiveDigestService(salt="unit-test-secret"),
        )
        first_request = self._build_request(path="/auth/token", method="POST")
        first_request.state.request_scope = RequestScope(
            request_id="request-1",
            trace_id=None,
            request_time_epoch=1,
            request_path="/auth/token",
            request_method="POST",
            authenticated_subject_id="subject-1",
        )
        second_request = self._build_request(path="/auth/token", method="POST")
        second_request.state.request_scope = RequestScope(
            request_id="request-2",
            trace_id=None,
            request_time_epoch=1,
            request_path="/auth/token",
            request_method="POST",
            authenticated_subject_id="subject-2",
        )

        first_result = guard.evaluate(
            request=first_request,
            limit=1,
            window_seconds=60,
            policy_name="auth_token",
            key_dimensions=[
                RateLimitKeyDimension.SUBJECT_ID,
                RateLimitKeyDimension.PATH_METHOD,
                RateLimitKeyDimension.AUTH_FIELD_DIGEST,
            ],
            auth_field_values=["tenant-a"],
        )
        second_result = guard.evaluate(
            request=second_request,
            limit=1,
            window_seconds=60,
            policy_name="auth_token",
            key_dimensions=[
                RateLimitKeyDimension.SUBJECT_ID,
                RateLimitKeyDimension.PATH_METHOD,
                RateLimitKeyDimension.AUTH_FIELD_DIGEST,
            ],
            auth_field_values=["tenant-a"],
        )
        third_result = guard.evaluate(
            request=first_request,
            limit=1,
            window_seconds=60,
            policy_name="auth_token",
            key_dimensions=[
                RateLimitKeyDimension.SUBJECT_ID,
                RateLimitKeyDimension.PATH_METHOD,
                RateLimitKeyDimension.AUTH_FIELD_DIGEST,
            ],
            auth_field_values=["tenant-a"],
        )

        assert first_result.subject_digest != second_result.subject_digest
        assert first_result.auth_field_digest is not None
        assert second_result.exceeded is False
        assert third_result.exceeded is True
        cache_store.close()

    def _build_request(self, *, path: str = "/health/live", method: str = "GET") -> Request:
        """
        构建测试请求。
        """

        return Request(
            {
                "type": "http",
                "method": method,
                "path": path,
                "headers": [],
                "client": ("127.0.0.1", 12345),
                "scheme": "http",
                "server": ("testserver", 80),
            }
        )
