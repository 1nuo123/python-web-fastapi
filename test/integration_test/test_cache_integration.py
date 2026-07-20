"""
测试缓存集成测试模块。
"""

from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.testing.test_app_factory import TestAppFactory
from src.core.auth_contract.auth_throttle_state_contract import AuthThrottleStatePayload
from src.core.cache_contract.cache_namespace_contract import CacheNamespace
from src.core.cache_contract.cache_policy_contract import CacheFailureMode
from src.infrastructure.cache.cache_key_builder import CacheKeyBuilder
from src.infrastructure.cache.cache_payload_codec import CachePayloadCodec
from src.infrastructure.cache.cache_service import (
    CacheDeleteRequest,
    CacheIncrementRequest,
    CacheReadRequest,
    CacheService,
    CacheWriteRequest,
)
from src.infrastructure.cache.redis_cache_store import RedisCacheStore
from src.infrastructure.testing.cache_policy_test_support import CachePolicyTestFactory
from test.redis_integration_support import (
    REDIS_INTEGRATION_MAX_CONNECTIONS,
    RedisIntegrationAvailability,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.usefixtures("integration_database"),
    pytest.mark.redis,
]


AUTH_TOKEN_PATH = "/auth/token"
REDIS_TEST_URL_ENV = "REDIS_TEST_URL"
REDIS_CACHE_URL = os.getenv(REDIS_TEST_URL_ENV, "redis://127.0.0.1:56379/0")
REDIS_CACHE_KEY_PREFIX = "integration_cache"
REDIS_AUTH_THROTTLE_KEY_PREFIX_TEMPLATE = "fastapi_web_skeleton_test_redis_{suffix}"
REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS = 2
REDIS_TTL_SECONDS = 1
REDIS_TTL_WAIT_SECONDS = 1.2
REDIS_INCREMENT_TTL_SECONDS = 5
REDIS_INCREMENT_OPERATION_COUNT = 20
REDIS_INCREMENT_WORKER_COUNT = 8


class TestCacheIntegration:
    """
    测试缓存集成测试集合，用于组织同一主题下的测试场景。
    """

    def test_redis_cache_service_should_read_write_and_expire_payload(self) -> None:
        """
        验证Redis缓存服务应读取写入与过期载荷。

        :returns: 无返回值。
        :rtype: None
        """

        RedisIntegrationAvailability.fail_when_unavailable(
            redis_url=REDIS_CACHE_URL,
            timeout_seconds=REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS,
        )
        redis_cache_store = RedisCacheStore(
            redis_url=REDIS_CACHE_URL,
            socket_connect_timeout_seconds=REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS,
        )
        cache_service = CacheService(
            cache_store=redis_cache_store,
            key_builder=CacheKeyBuilder(key_prefix=REDIS_CACHE_KEY_PREFIX),
            payload_codec=CachePayloadCodec(),
            policy_resolver=CachePolicyTestFactory().build_resolver(
                runtime_default_ttl_seconds=REDIS_TTL_SECONDS,
            ),
            default_ttl_seconds=REDIS_TTL_SECONDS,
        )
        cache_write_request = CacheWriteRequest(
            namespace=CacheNamespace.AUTH_THROTTLE,
            key_parts=["issue_access_token", "redis-digest"],
            payload=AuthThrottleStatePayload(
                failure_count=1,
                locked_until_epoch=None,
            ),
            ttl_seconds=REDIS_TTL_SECONDS,
        )
        try:
            cache_service.write_payload(cache_write_request)
            hit_result = cache_service.read_payload(
                CacheReadRequest(
                    namespace=CacheNamespace.AUTH_THROTTLE,
                    key_parts=["issue_access_token", "redis-digest"],
                    payload_type=AuthThrottleStatePayload,
                )
            )
            assert hit_result.hit is True
            assert hit_result.payload is not None
            assert hit_result.payload.failure_count == 1

            time.sleep(REDIS_TTL_WAIT_SECONDS)
            miss_result = cache_service.read_payload(
                CacheReadRequest(
                    namespace=CacheNamespace.AUTH_THROTTLE,
                    key_parts=["issue_access_token", "redis-digest"],
                    payload_type=AuthThrottleStatePayload,
                )
            )
            assert miss_result.hit is False
            assert miss_result.payload is None
            assert (
                cache_service._policy_resolver.resolve(  # noqa: SLF001
                    CacheNamespace.QUERY_RESULT
                ).failure_mode
                == CacheFailureMode.FAIL_OPEN
            )
        finally:
            redis_cache_store.close()

    def test_auth_failure_throttle_with_redis_backend_should_lock_request(self) -> None:
        """
        验证鉴权失败节流携带Redis后端应锁定请求。

        :returns: 无返回值。
        :rtype: None
        """

        RedisIntegrationAvailability.fail_when_unavailable(
            redis_url=REDIS_CACHE_URL,
            timeout_seconds=REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS,
        )
        app = TestAppFactory().create(
            overrides={
                "runtime": {
                    "cache": {
                        "backend": "redis",
                        "key_prefix": REDIS_AUTH_THROTTLE_KEY_PREFIX_TEMPLATE.format(
                            suffix=uuid4()
                        ),
                        "backend_detail": {
                            "kind": "redis_cache_backend",
                            "schema_version": "1.0",
                            "redis_url": REDIS_CACHE_URL,
                            "socket_connect_timeout_seconds": (
                                REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS
                            ),
                            "max_connections": REDIS_INTEGRATION_MAX_CONNECTIONS,
                        },
                    }
                }
            }
        )

        with TestClient(app) as client:
            for _ in range(3):
                response = client.post(
                    AUTH_TOKEN_PATH,
                    json={"username": "admin", "password": "wrong-password"},
                )
                assert response.status_code == 401

            throttled_response = client.post(
                AUTH_TOKEN_PATH,
                json={"username": "admin", "password": "wrong-password"},
            )

            assert throttled_response.status_code == 429
            assert throttled_response.json()["data"]["error_code"] == "auth.request.throttled"

    def test_redis_increment_counter_should_not_lose_concurrent_updates(self) -> None:
        """
        验证 Redis 原子递增在并发调用下不丢计数。

        :returns: 无返回值。
        :rtype: None
        """

        RedisIntegrationAvailability.fail_when_unavailable(
            redis_url=REDIS_CACHE_URL,
            timeout_seconds=REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS,
        )
        RedisIntegrationAvailability.fail_when_unavailable(
            redis_url=REDIS_CACHE_URL,
            timeout_seconds=REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS,
        )
        redis_cache_store = RedisCacheStore(
            redis_url=REDIS_CACHE_URL,
            socket_connect_timeout_seconds=REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS,
        )
        cache_service = CacheService(
            cache_store=redis_cache_store,
            key_builder=CacheKeyBuilder(key_prefix=REDIS_CACHE_KEY_PREFIX),
            payload_codec=CachePayloadCodec(),
            policy_resolver=CachePolicyTestFactory().build_resolver(
                runtime_default_ttl_seconds=REDIS_INCREMENT_TTL_SECONDS,
            ),
            default_ttl_seconds=REDIS_INCREMENT_TTL_SECONDS,
        )
        cache_increment_request = CacheIncrementRequest(
            namespace=CacheNamespace.AUTH_THROTTLE,
            key_parts=["issue_access_token", f"redis-increment-{uuid4()}"],
            ttl_seconds=REDIS_INCREMENT_TTL_SECONDS,
        )
        try:
            with ThreadPoolExecutor(max_workers=REDIS_INCREMENT_WORKER_COUNT) as executor:
                results = list(
                    executor.map(
                        lambda _index: cache_service.increment_counter(cache_increment_request),
                        range(REDIS_INCREMENT_OPERATION_COUNT),
                    )
                )

            assert max(results) == REDIS_INCREMENT_OPERATION_COUNT
            assert len(set(results)) == REDIS_INCREMENT_OPERATION_COUNT
        finally:
            cache_service.delete_payload(
                CacheDeleteRequest(
                    namespace=CacheNamespace.AUTH_THROTTLE,
                    key_parts=cache_increment_request.key_parts,
                )
            )
            redis_cache_store.close()
