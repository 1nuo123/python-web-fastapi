"""确定性内存 fenced lease 实现。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from src.core.concurrency_contract.fenced_lease_contract import (
    FencedLease,
    FencedLeasePort,
    FencedLeaseRequest,
)


class MemoryFencedLeaseStore(FencedLeasePort):
    """按资源保持单调 token，旧 owner 不能删除新租约。"""

    def __init__(self) -> None:
        self._leases: dict[str, FencedLease] = {}
        self._tokens: dict[str, int] = {}
        self._lock = asyncio.Lock()

    async def acquire(self, request: FencedLeaseRequest) -> FencedLease | None:
        async with self._lock:
            current = self._active(request.resource_key)
            if current is not None:
                return None
            token = self._tokens.get(request.resource_key, 0) + 1
            self._tokens[request.resource_key] = token
            lease = FencedLease(
                resource_key=request.resource_key,
                owner=request.owner,
                fencing_token=token,
                expires_at=datetime.now(UTC) + timedelta(seconds=request.ttl_seconds),
            )
            self._leases[request.resource_key] = lease
            return lease

    async def renew(self, lease: FencedLease, ttl_seconds: int) -> FencedLease | None:
        async with self._lock:
            current = self._active(lease.resource_key)
            if not self._matches(current, lease):
                return None
            renewed = lease.model_copy(
                update={"expires_at": datetime.now(UTC) + timedelta(seconds=ttl_seconds)}
            )
            self._leases[lease.resource_key] = renewed
            return renewed

    async def release(self, lease: FencedLease) -> bool:
        async with self._lock:
            current = self._active(lease.resource_key)
            if not self._matches(current, lease):
                return False
            self._leases.pop(lease.resource_key, None)
            return True

    async def read(self, resource_key: str) -> FencedLease | None:
        async with self._lock:
            return self._active(resource_key)

    def _active(self, resource_key: str) -> FencedLease | None:
        lease = self._leases.get(resource_key)
        if lease is not None and lease.expires_at <= datetime.now(UTC):
            self._leases.pop(resource_key, None)
            return None
        return lease

    def _matches(self, current: FencedLease | None, expected: FencedLease) -> bool:
        return (
            current is not None
            and current.owner == expected.owner
            and current.fencing_token == expected.fencing_token
        )
