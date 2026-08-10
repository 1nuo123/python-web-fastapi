"""
Redis 集成测试依赖检查辅助模块。
"""

from __future__ import annotations

import asyncio

from src.core.redis_resource_contract.redis_resource_runtime_contract import (
    RedisResourceRuntimeDetail,
)
from src.infrastructure.resource_slot.shared_redis_resource import SharedRedisResource

REDIS_INTEGRATION_UNAVAILABLE_REASON = "Redis 集成测试依赖未可用。"
REDIS_INTEGRATION_MAX_CONNECTIONS = 8
REDIS_INTEGRATION_OPERATION_TIMEOUT_SECONDS = 5
REDIS_INTEGRATION_HEALTH_TIMEOUT_SECONDS = 2


class RedisIntegrationAvailability:
    """
    Redis 集成测试可用性检查器。
    """

    @staticmethod
    def fail_when_unavailable(
        *,
        redis_url: str,
        timeout_seconds: int,
        reason: str = REDIS_INTEGRATION_UNAVAILABLE_REASON,
    ) -> None:
        """
        Redis 不可达时让真实依赖回归明确失败。
        """

        resource = RedisIntegrationAvailability.create_resource(
            redis_url=redis_url,
            timeout_seconds=timeout_seconds,
        )
        try:
            resource.assert_sync_available()
        except RuntimeError as exc:
            raise RuntimeError(f"{reason} {exc}") from exc
        finally:
            RedisIntegrationAvailability.close_resource(resource)

    @staticmethod
    def create_resource(*, redis_url: str, timeout_seconds: int) -> SharedRedisResource:
        """为单个测试创建遵循生产所有权模型的共享 Redis 资源。"""

        return SharedRedisResource(
            RedisResourceRuntimeDetail(
                url=redis_url,
                connect_timeout_seconds=timeout_seconds,
                operation_timeout_seconds=REDIS_INTEGRATION_OPERATION_TIMEOUT_SECONDS,
                sync_max_connections=REDIS_INTEGRATION_MAX_CONNECTIONS,
                async_max_connections=REDIS_INTEGRATION_MAX_CONNECTIONS,
                health_probe_timeout_seconds=REDIS_INTEGRATION_HEALTH_TIMEOUT_SECONDS,
                require_tls_in_production=False,
            )
        )

    @staticmethod
    def close_resource(resource: SharedRedisResource) -> None:
        """完整关闭测试拥有的同步与异步 Redis client。"""

        asyncio.run(resource.close())
