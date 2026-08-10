"""
测试缓存运行时路径测试模块。
"""

from __future__ import annotations

import pytest

from src.core.auth_contract.auth_throttle_state_contract import AuthThrottleStatePayload
from src.core.cache_contract.cache_namespace_contract import CacheNamespace
from src.core.cache_contract.cache_policy_contract import (
    AUTH_THROTTLE_CACHE_POLICY_DETAIL_KIND,
    CACHE_POLICY_HEADER_KIND,
    CACHE_POLICY_SCHEMA_VERSION,
    QUERY_RESULT_CACHE_POLICY_DETAIL_KIND,
    CacheFailureMode,
)
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.infrastructure.cache.cache_key_builder import CacheKeyBuilder
from src.infrastructure.cache.cache_payload_codec import CachePayloadCodec
from src.infrastructure.cache.cache_service import (
    CacheReadRequest,
    CacheService,
    CacheWriteRequest,
)
from src.infrastructure.settings.app_settings_loader import AppSettingsLoader
from src.infrastructure.settings.application_settings import AppEnvironment
from src.infrastructure.testing.cache_policy_test_support import CachePolicyTestFactory
from src.infrastructure.testing.fake_cache_store import FakeCacheStore
from src.infrastructure.testing.fake_clock import FakeClock

DEFAULT_CACHE_TTL_SECONDS = 30
TEST_CACHE_KEY_PREFIX = "path_cache"


class TestCacheRuntimePath:
    """
    测试缓存运行时路径测试集合，用于组织同一主题下的测试场景。
    """

    def test_loader_when_cache_backend_detail_mismatched_should_fail(self) -> None:
        """
        验证加载器当缓存后端详情不匹配应失败。

        :returns: 无返回值。
        :rtype: None
        """

        loader = AppSettingsLoader()

        with pytest.raises(HttpFaultException) as fault:
            loader.load_from_mapping(
                environment=AppEnvironment.TEST,
                overrides={
                    "runtime": {
                        "cache": {
                            "backend": "memory",
                            "backend_detail": {
                                "kind": "redis_cache_backend",
                                "schema_version": "1.0",
                            },
                        }
                    }
                },
            )

        assert "memory" in str(fault.value.detail)

    def test_loader_when_cache_key_prefix_empty_should_fail(self) -> None:
        """
        验证加载器当缓存键前缀空值应失败。

        :returns: 无返回值。
        :rtype: None
        """

        loader = AppSettingsLoader()

        with pytest.raises(HttpFaultException) as fault:
            loader.load_from_mapping(
                environment=AppEnvironment.TEST,
                overrides={"runtime": {"cache": {"key_prefix": "   "}}},
            )

        assert "runtime.cache.key_prefix 不能为空" in str(fault.value.detail)

    def test_loader_when_cache_namespace_policies_valid_should_load(self) -> None:
        """
        验证加载器应加载合法缓存命名空间策略。

        :returns: 无返回值。
        :rtype: None
        """

        settings = AppSettingsLoader().load_from_mapping(
            environment=AppEnvironment.TEST,
            overrides={},
        )

        query_policy = [
            policy
            for policy in settings.runtime.cache.namespace_policies
            if policy.header.detail_kind == QUERY_RESULT_CACHE_POLICY_DETAIL_KIND
        ][0]
        assert query_policy.detail.failure_mode == CacheFailureMode.FAIL_OPEN

    def test_loader_when_cache_namespace_policy_mismatched_should_fail(self) -> None:
        """
        验证加载器当缓存策略公共头与扩展字段不一致应失败。

        :returns: 无返回值。
        :rtype: None
        """

        with pytest.raises(HttpFaultException) as fault:
            AppSettingsLoader().load_from_mapping(
                environment=AppEnvironment.TEST,
                overrides={
                    "runtime": {
                        "cache": {
                            "namespace_policies": [
                                {
                                    "header": {
                                        "kind": CACHE_POLICY_HEADER_KIND,
                                        "schema_version": CACHE_POLICY_SCHEMA_VERSION,
                                        "detail_kind": QUERY_RESULT_CACHE_POLICY_DETAIL_KIND,
                                        "namespace": CacheNamespace.AUTH_THROTTLE,
                                    },
                                    "detail": {
                                        "kind": AUTH_THROTTLE_CACHE_POLICY_DETAIL_KIND,
                                        "schema_version": CACHE_POLICY_SCHEMA_VERSION,
                                        "namespace": CacheNamespace.AUTH_THROTTLE,
                                        "default_ttl_seconds": DEFAULT_CACHE_TTL_SECONDS,
                                        "failure_mode": CacheFailureMode.FAIL_CLOSED,
                                    },
                                }
                            ]
                        }
                    }
                },
            )

        assert "detail_kind" in str(fault.value.detail)

    def test_cache_service_when_raw_value_invalid_should_clear_and_return_miss(self) -> None:
        """
        验证缓存服务当原始值无效应清理与返回未命中。

        :returns: 无返回值。
        :rtype: None
        """

        fake_clock = FakeClock()
        cache_store = FakeCacheStore(timer=fake_clock.now)
        cache_service = CacheService(
            cache_store=cache_store,
            key_builder=CacheKeyBuilder(key_prefix=TEST_CACHE_KEY_PREFIX),
            payload_codec=CachePayloadCodec(),
            policy_resolver=CachePolicyTestFactory().build_resolver(
                runtime_default_ttl_seconds=DEFAULT_CACHE_TTL_SECONDS,
            ),
            default_ttl_seconds=DEFAULT_CACHE_TTL_SECONDS,
        )
        cache_key = CacheKeyBuilder(key_prefix=TEST_CACHE_KEY_PREFIX).build(
            namespace=CacheNamespace.AUTH_THROTTLE,
            key_parts=["refresh_access_token", "digest"],
        )
        cache_store.set_value(cache_key, "invalid-json", DEFAULT_CACHE_TTL_SECONDS)

        read_result = cache_service.read_payload(
            CacheReadRequest(
                namespace=CacheNamespace.AUTH_THROTTLE,
                key_parts=["refresh_access_token", "digest"],
                payload_type=AuthThrottleStatePayload,
            )
        )

        assert read_result.hit is False
        assert read_result.payload is None
        assert cache_store.get_value(cache_key) is None

    def test_cache_service_when_ttl_elapsed_should_follow_miss_path(self) -> None:
        """
        验证缓存服务当TTL耗时应遵循未命中路径。

        :returns: 无返回值。
        :rtype: None
        """

        fake_clock = FakeClock()
        cache_store = FakeCacheStore(timer=fake_clock.now)
        cache_service = CacheService(
            cache_store=cache_store,
            key_builder=CacheKeyBuilder(key_prefix=TEST_CACHE_KEY_PREFIX),
            payload_codec=CachePayloadCodec(),
            policy_resolver=CachePolicyTestFactory().build_resolver(
                runtime_default_ttl_seconds=DEFAULT_CACHE_TTL_SECONDS,
            ),
            default_ttl_seconds=DEFAULT_CACHE_TTL_SECONDS,
        )
        cache_service.write_payload(
            request=self._build_write_request(),
        )

        fake_clock.advance(DEFAULT_CACHE_TTL_SECONDS + 0.1)
        read_result = cache_service.read_payload(
            CacheReadRequest(
                namespace=CacheNamespace.AUTH_THROTTLE,
                key_parts=["refresh_access_token", "digest"],
                payload_type=AuthThrottleStatePayload,
            )
        )

        assert read_result.hit is False
        assert read_result.payload is None

    def _build_write_request(self) -> CacheWriteRequest:
        """
        构建写入请求。

        :returns: 返回当前操作结果。
        :rtype: CacheWriteRequest
        """

        return CacheWriteRequest(
            namespace=CacheNamespace.AUTH_THROTTLE,
            key_parts=["refresh_access_token", "digest"],
            payload=AuthThrottleStatePayload(
                failure_count=1,
                locked_until_epoch=None,
            ),
        )
