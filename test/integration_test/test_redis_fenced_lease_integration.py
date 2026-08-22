"""Redis fenced lease 的真实实例集成测试。"""

from __future__ import annotations

import os
from collections.abc import Awaitable
from typing import cast
from uuid import uuid4

import pytest
from redis.asyncio import Redis

from src.core.concurrency_contract.fenced_lease_contract import FencedLeaseRequest
from src.infrastructure.concurrency.redis_fenced_lease_store import (
    FENCED_LEASE_NAMESPACE,
    FENCED_LEASE_SEPARATOR,
    FENCED_TOKEN_NAMESPACE,
    RedisFencedLeaseStore,
)

pytestmark = [pytest.mark.integration, pytest.mark.redis]

REDIS_TEST_URL_ENVIRONMENT_VARIABLE = "REDIS_TEST_URL"
DEFAULT_REDIS_TEST_URL = "redis://127.0.0.1:56379/0"
REDIS_CONNECTION_TIMEOUT_SECONDS = 2
LEASE_TTL_SECONDS = 60


class TestRedisFencedLeaseIntegration:
    """验证真实 Redis 的 Lua CAS 与 fencing token 语义。"""

    @pytest.mark.asyncio
    async def test_fenced_lease_should_reject_stale_owner_and_advance_generation(self) -> None:
        """同一资源只能由当前 owner 续租或释放，重新认领必须递增代次。"""

        redis_url = os.getenv(REDIS_TEST_URL_ENVIRONMENT_VARIABLE, DEFAULT_REDIS_TEST_URL)
        client = Redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=REDIS_CONNECTION_TIMEOUT_SECONDS,
        )
        key_prefix = f"integration_codex_fenced_lease_{uuid4().hex}"
        resource_key = "owner-thread-turn"
        store = RedisFencedLeaseStore(client=client, key_prefix=key_prefix)
        first_request = FencedLeaseRequest(
            resource_key=resource_key,
            owner="agent-one",
            ttl_seconds=LEASE_TTL_SECONDS,
        )
        second_request = FencedLeaseRequest(
            resource_key=resource_key,
            owner="agent-two",
            ttl_seconds=LEASE_TTL_SECONDS,
        )
        try:
            assert await cast(Awaitable[bool], client.ping()) is True
            first_lease = await store.acquire(first_request)

            assert first_lease is not None
            assert await store.acquire(second_request) is None
            assert await store.renew(first_lease, LEASE_TTL_SECONDS) is not None
            assert await store.release(first_lease) is True

            second_lease = await store.acquire(second_request)

            assert second_lease is not None
            assert second_lease.fencing_token == first_lease.fencing_token + 1
            assert await store.renew(first_lease, LEASE_TTL_SECONDS) is None
            assert await store.release(first_lease) is False
            persisted_lease = await store.read(resource_key)

            assert persisted_lease is not None
            assert persisted_lease.owner == second_lease.owner
            assert persisted_lease.fencing_token == second_lease.fencing_token
        finally:
            await client.delete(
                self._build_lease_key(key_prefix, resource_key),
                self._build_token_key(key_prefix, resource_key),
            )
            await client.aclose()

    @staticmethod
    def _build_lease_key(key_prefix: str, resource_key: str) -> str:
        """构造测试专属 lease key，确保清理范围不触及其他运行态。"""

        return FENCED_LEASE_SEPARATOR.join((key_prefix, FENCED_LEASE_NAMESPACE, resource_key))

    @staticmethod
    def _build_token_key(key_prefix: str, resource_key: str) -> str:
        """构造测试专属 fencing token key，确保代次计数不残留。"""

        return FENCED_LEASE_SEPARATOR.join((key_prefix, FENCED_TOKEN_NAMESPACE, resource_key))
