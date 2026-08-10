"""基于共享 redis-py client 的 fenced lease 实现。"""

from __future__ import annotations

import json
from collections.abc import Awaitable
from datetime import UTC, datetime, timedelta
from typing import Final, cast

from redis.asyncio import Redis
from redis.exceptions import RedisError

from src.core.concurrency_contract.fenced_lease_contract import (
    FencedLease,
    FencedLeasePort,
    FencedLeaseRequest,
)

FENCED_LEASE_NAMESPACE: Final = "fenced_lease"
FENCED_TOKEN_NAMESPACE: Final = "fenced_token"
FENCED_LEASE_SEPARATOR: Final = ":"
FENCED_LEASE_ACQUIRE_SCRIPT: Final = """
if redis.call('EXISTS', KEYS[1]) == 1 then return nil end
local token = redis.call('INCR', KEYS[2])
local payload = cjson.encode({owner=ARGV[1], fencing_token=token})
redis.call('SET', KEYS[1], payload, 'EX', tonumber(ARGV[2]), 'NX')
return token
"""
FENCED_LEASE_RENEW_SCRIPT: Final = """
local payload = redis.call('GET', KEYS[1])
if not payload then return 0 end
local current = cjson.decode(payload)
if current.owner ~= ARGV[1] or tonumber(current.fencing_token) ~= tonumber(ARGV[2]) then return 0 end
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[3]))
return 1
"""
FENCED_LEASE_RELEASE_SCRIPT: Final = """
local payload = redis.call('GET', KEYS[1])
if not payload then return 0 end
local current = cjson.decode(payload)
if current.owner ~= ARGV[1] or tonumber(current.fencing_token) ~= tonumber(ARGV[2]) then return 0 end
redis.call('DEL', KEYS[1])
return 1
"""


class RedisFencedLeaseStore(FencedLeasePort):
    """只在该通用 adapter 内持有 lease Lua，不拥有 Redis client。"""

    def __init__(self, *, client: Redis, key_prefix: str) -> None:
        self._client = client
        self._key_prefix = key_prefix

    async def acquire(self, request: FencedLeaseRequest) -> FencedLease | None:
        try:
            token = await cast(
                Awaitable[int | None],
                self._client.eval(
                    FENCED_LEASE_ACQUIRE_SCRIPT,
                    2,
                    self._lease_key(request.resource_key),
                    self._token_key(request.resource_key),
                    request.owner,
                    request.ttl_seconds,
                ),
            )
        except RedisError as exc:
            raise RuntimeError("Redis fenced lease不可用。") from exc
        if token is None:
            return None
        return FencedLease(
            resource_key=request.resource_key,
            owner=request.owner,
            fencing_token=int(token),
            expires_at=datetime.now(UTC) + timedelta(seconds=request.ttl_seconds),
        )

    async def renew(self, lease: FencedLease, ttl_seconds: int) -> FencedLease | None:
        try:
            changed = await cast(
                Awaitable[int],
                self._client.eval(
                    FENCED_LEASE_RENEW_SCRIPT,
                    1,
                    self._lease_key(lease.resource_key),
                    lease.owner,
                    lease.fencing_token,
                    ttl_seconds,
                ),
            )
        except RedisError as exc:
            raise RuntimeError("Redis fenced lease不可用。") from exc
        if int(changed) != 1:
            return None
        return lease.model_copy(
            update={"expires_at": datetime.now(UTC) + timedelta(seconds=ttl_seconds)}
        )

    async def release(self, lease: FencedLease) -> bool:
        try:
            deleted = await cast(
                Awaitable[int],
                self._client.eval(
                    FENCED_LEASE_RELEASE_SCRIPT,
                    1,
                    self._lease_key(lease.resource_key),
                    lease.owner,
                    lease.fencing_token,
                ),
            )
        except RedisError as exc:
            raise RuntimeError("Redis fenced lease不可用。") from exc
        return int(deleted) == 1

    async def read(self, resource_key: str) -> FencedLease | None:
        try:
            key = self._lease_key(resource_key)
            payload = await cast(Awaitable[str | None], self._client.get(key))
            ttl = await cast(Awaitable[int], self._client.ttl(key))
        except RedisError as exc:
            raise RuntimeError("Redis fenced lease不可用。") from exc
        if payload is None or int(ttl) <= 0:
            return None
        decoded = json.loads(str(payload))
        if not isinstance(decoded, dict):
            raise ValueError("Redis fenced lease记录结构无效。")
        return FencedLease(
            resource_key=resource_key,
            owner=str(decoded["owner"]),
            fencing_token=int(decoded["fencing_token"]),
            expires_at=datetime.now(UTC) + timedelta(seconds=int(ttl)),
        )

    def _lease_key(self, resource_key: str) -> str:
        return FENCED_LEASE_SEPARATOR.join((self._key_prefix, FENCED_LEASE_NAMESPACE, resource_key))

    def _token_key(self, resource_key: str) -> str:
        return FENCED_LEASE_SEPARATOR.join((self._key_prefix, FENCED_TOKEN_NAMESPACE, resource_key))
