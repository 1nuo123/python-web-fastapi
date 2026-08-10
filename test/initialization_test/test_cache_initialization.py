"""
测试缓存初始化测试模块。
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from src.api.testing.test_app_factory import TestAppFactory
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.infrastructure.cache.cache_policy_resolver import CachePolicyResolver
from src.infrastructure.cache.redis_cache_store import RedisCacheStore
from src.infrastructure.settings.app_settings_loader import AppSettingsLoader
from src.infrastructure.settings.application_settings import AppEnvironment
from test.redis_integration_support import (
    REDIS_INTEGRATION_MAX_CONNECTIONS,
    RedisIntegrationAvailability,
)

REDIS_TEST_URL_ENV = "REDIS_TEST_URL"
REDIS_CACHE_URL = os.getenv(REDIS_TEST_URL_ENV, "redis://127.0.0.1:56379/0")
REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS = 2


class TestCacheInitialization:
    """
    测试缓存初始化测试集合，用于组织同一主题下的测试场景。
    """

    def test_app_startup_should_prepare_cache_service_under_memory_backend(self) -> None:
        """
        验证应用启动应准备缓存服务在内存后端。

        :returns: 无返回值。
        :rtype: None
        """

        app = TestAppFactory().create()

        with TestClient(app):
            resource_mount = app.state.container.resource_mount
            assert resource_mount.get_cache_store() is not None
            assert resource_mount.get_cache_service() is not None
            assert isinstance(
                resource_mount.get_cache_service()._policy_resolver,  # noqa: SLF001
                CachePolicyResolver,
            )

    def test_loader_when_memory_cache_max_entries_invalid_should_fail(self) -> None:
        """
        验证加载器当内存缓存最大条目无效应失败。

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
                            "backend_detail": {
                                "kind": "memory_cache_backend",
                                "schema_version": "1.0",
                                "max_entries": 0,
                            }
                        }
                    }
                },
            )

        assert "max_entries" in str(fault.value.detail)

    @pytest.mark.integration
    @pytest.mark.redis
    def test_app_startup_when_redis_backend_enabled_should_prepare_redis_cache_resources(
        self,
    ) -> None:
        """
        验证应用启动当Redis后端启用应准备Redis缓存资源集合。

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
                    "redis_resource": {
                        "header": {"enabled": True},
                        "detail": {
                            "url": REDIS_CACHE_URL,
                            "connect_timeout_seconds": (REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS),
                            "sync_max_connections": REDIS_INTEGRATION_MAX_CONNECTIONS,
                            "async_max_connections": REDIS_INTEGRATION_MAX_CONNECTIONS,
                        },
                    },
                    "cache": {
                        "backend": "redis",
                        "key_prefix": "fastapi_web_skeleton_test_redis",
                        "backend_detail": {
                            "kind": "redis_cache_backend",
                            "schema_version": "1.0",
                        },
                    },
                }
            }
        )

        with TestClient(app):
            resource_mount = app.state.container.resource_mount
            assert isinstance(resource_mount.get_cache_store(), RedisCacheStore)
            assert resource_mount.get_cache_service() is not None
