"""
Redis 集成测试依赖检查辅助模块。
"""

from __future__ import annotations

from redis.exceptions import RedisError

from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.infrastructure.cache.redis_cache_store import RedisCacheStore

REDIS_INTEGRATION_UNAVAILABLE_REASON = "Redis 集成测试依赖未可用。"
REDIS_INTEGRATION_MAX_CONNECTIONS = 8


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

        cache_store = RedisCacheStore(
            redis_url=redis_url,
            socket_connect_timeout_seconds=timeout_seconds,
        )
        try:
            cache_store.assert_available()
        except HttpFaultException as exc:
            raise RuntimeError(f"{reason} {exc.message}") from exc
        except RedisError as exc:
            raise RuntimeError(f"{reason} {exc}") from exc
        finally:
            cache_store.close()
