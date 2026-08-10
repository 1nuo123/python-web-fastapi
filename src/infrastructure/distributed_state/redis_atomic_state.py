"""基于共享异步 Redis client 的通用原子状态适配器。"""

from __future__ import annotations

from collections.abc import Awaitable
from datetime import UTC, datetime
from typing import cast

from redis.asyncio import Redis

from src.core.distributed_state_contract.atomic_state_contract import (
    AtomicStatePort,
    AtomicStateRecord,
)

ATOMIC_STATE_CREATE_SCRIPT = """
if redis.call('EXISTS', KEYS[1]) == 1 then return 0 end
redis.call('HSET', KEYS[1], 'value', ARGV[1], 'version', ARGV[2], 'expires_at', ARGV[3])
if ARGV[4] ~= '' then redis.call('EXPIRE', KEYS[1], ARGV[4]) end
return 1
"""
ATOMIC_STATE_CREATE_WITH_INDEX_SCRIPT = """
if redis.call('EXISTS', KEYS[1]) == 1 or redis.call('EXISTS', KEYS[2]) == 1 then
    return 0
end
redis.call('HSET', KEYS[1], 'value', ARGV[1], 'version', ARGV[2], 'expires_at', ARGV[3])
redis.call('HSET', KEYS[2], 'value', ARGV[4], 'version', ARGV[5], 'expires_at', ARGV[6])
if ARGV[7] ~= '' then redis.call('EXPIRE', KEYS[1], ARGV[7]) end
if ARGV[8] ~= '' then redis.call('EXPIRE', KEYS[2], ARGV[8]) end
return 1
"""
ATOMIC_STATE_CAS_SCRIPT = """
local current = redis.call('HGET', KEYS[1], 'version')
if not current or tonumber(current) ~= tonumber(ARGV[1]) then return 0 end
redis.call('HSET', KEYS[1], 'value', ARGV[2], 'version', ARGV[3], 'expires_at', ARGV[4])
if ARGV[5] ~= '' then redis.call('EXPIRE', KEYS[1], ARGV[5]) end
return 1
"""
ATOMIC_STATE_DELETE_SCRIPT = """
local current = redis.call('HGET', KEYS[1], 'version')
if not current or tonumber(current) ~= tonumber(ARGV[1]) then return 0 end
return redis.call('DEL', KEYS[1])
"""


class RedisAtomicState(AtomicStatePort):
    """使用 Lua 保证状态转换原子性，不拥有 Redis client 生命周期。"""

    def __init__(self, *, client: Redis, key_prefix: str) -> None:
        self._client = client
        self._key_prefix = key_prefix

    async def read(self, key: str) -> AtomicStateRecord | None:
        values = await cast(Awaitable[dict[str, str]], self._client.hgetall(self._key(key)))
        if not values:
            return None
        expires_at_epoch = float(values["expires_at"]) if values.get("expires_at") else None
        expires_at = (
            datetime.fromtimestamp(expires_at_epoch, tz=UTC)
            if expires_at_epoch is not None
            else None
        )
        return AtomicStateRecord(
            key=key,
            value=values["value"],
            version=int(values["version"]),
            expires_at=expires_at,
        )

    async def create(self, record: AtomicStateRecord) -> bool:
        ttl = self._ttl(record.expires_at)
        result = await cast(
            Awaitable[int],
            self._client.eval(
                ATOMIC_STATE_CREATE_SCRIPT,
                1,
                self._key(record.key),
                record.value,
                record.version,
                record.expires_at.timestamp() if record.expires_at else "",
                ttl,
            ),
        )
        return int(result) == 1

    async def create_with_index(
        self,
        *,
        record: AtomicStateRecord,
        index_record: AtomicStateRecord,
    ) -> bool:
        """通过一段 Lua 原子创建主记录和唯一索引。"""

        result = await cast(
            Awaitable[int],
            self._client.eval(
                ATOMIC_STATE_CREATE_WITH_INDEX_SCRIPT,
                2,
                self._key(record.key),
                self._key(index_record.key),
                record.value,
                record.version,
                record.expires_at.timestamp() if record.expires_at else "",
                index_record.value,
                index_record.version,
                index_record.expires_at.timestamp() if index_record.expires_at else "",
                self._ttl(record.expires_at),
                self._ttl(index_record.expires_at),
            ),
        )
        return int(result) == 1

    async def compare_and_set(
        self,
        *,
        key: str,
        expected_version: int,
        next_value: str,
        expires_at: datetime | None,
    ) -> AtomicStateRecord | None:
        next_version = expected_version + 1
        result = await cast(
            Awaitable[int],
            self._client.eval(
                ATOMIC_STATE_CAS_SCRIPT,
                1,
                self._key(key),
                expected_version,
                next_value,
                next_version,
                expires_at.timestamp() if expires_at else "",
                self._ttl(expires_at),
            ),
        )
        if int(result) != 1:
            return None
        return AtomicStateRecord(
            key=key,
            value=next_value,
            version=next_version,
            expires_at=expires_at,
        )

    async def delete(self, *, key: str, expected_version: int) -> bool:
        result = await cast(
            Awaitable[int],
            self._client.eval(
                ATOMIC_STATE_DELETE_SCRIPT,
                1,
                self._key(key),
                expected_version,
            ),
        )
        return int(result) == 1

    def _key(self, key: str) -> str:
        return f"{self._key_prefix}:atomic:{key}"

    def _ttl(self, expires_at: datetime | None) -> str:
        if expires_at is None:
            return ""
        return str(max(1, int((expires_at - datetime.now(UTC)).total_seconds())))
