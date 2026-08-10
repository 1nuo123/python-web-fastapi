"""进程唯一 sync/async Redis client 生命周期。"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import cast

from redis import Redis as SyncRedis
from redis.asyncio import Redis as AsyncRedis
from redis.exceptions import RedisError

from src.core.redis_resource_contract.redis_resource_runtime_contract import (
    RedisResourceRuntimeDetail,
)


class SharedRedisResource:
    """只由共享资源生命周期创建、探测和关闭 Redis clients。"""

    def __init__(self, settings: RedisResourceRuntimeDetail) -> None:
        self._settings = settings
        self._sync_client: SyncRedis = SyncRedis.from_url(
            settings.url,
            decode_responses=True,
            encoding="utf-8",
            socket_connect_timeout=settings.connect_timeout_seconds,
            socket_timeout=settings.operation_timeout_seconds,
            max_connections=settings.sync_max_connections,
        )
        self._async_client: AsyncRedis = AsyncRedis.from_url(
            settings.url,
            decode_responses=True,
            encoding="utf-8",
            socket_connect_timeout=settings.connect_timeout_seconds,
            socket_timeout=settings.operation_timeout_seconds,
            max_connections=settings.async_max_connections,
        )
        self._closed = False

    @property
    def sync_client(self) -> SyncRedis:
        """返回共享同步 client。"""

        if self._closed:
            raise RuntimeError("共享Redis资源已经关闭。")
        return self._sync_client

    @property
    def async_client(self) -> AsyncRedis:
        """返回共享异步 client。"""

        if self._closed:
            raise RuntimeError("共享Redis资源已经关闭。")
        return self._async_client

    def assert_sync_available(self) -> None:
        """同步探测 Redis。"""

        try:
            self.sync_client.ping()
        except RedisError as exc:
            raise RuntimeError("共享Redis资源同步探测失败。") from exc

    async def assert_async_available(self) -> None:
        """异步探测 Redis。"""

        try:
            await cast(Awaitable[bool], self.async_client.ping())
        except RedisError as exc:
            raise RuntimeError("共享Redis资源异步探测失败。") from exc

    async def close(self) -> None:
        """按异步、同步顺序关闭两个共享 client。"""

        if self._closed:
            return
        self._closed = True
        await self._async_client.aclose()
        self._sync_client.close()
