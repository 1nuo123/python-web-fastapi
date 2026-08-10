"""Codex host presence 到通用 fenced lease 的薄适配器。"""

from __future__ import annotations

import asyncio
from uuid import UUID

from src.core.codex_contract.presence_contract import (
    CodexHostPresence,
    CodexHostPresenceOwner,
)
from src.core.concurrency_contract.fenced_lease_contract import (
    FencedLease,
    FencedLeasePort,
    FencedLeaseRequest,
)

CODEX_HOST_PRESENCE_NAMESPACE = "codex:host_presence"


class CodexHostPresenceAdapter:
    """只映射 host/instance/connection epoch，不实现租约算法。"""

    def __init__(self, *, store: FencedLeasePort, ttl_seconds: int) -> None:
        self._store = store
        self._ttl_seconds = ttl_seconds

    async def acquire(self, owner: CodexHostPresenceOwner) -> CodexHostPresence:
        lease = await self._store.acquire(
            FencedLeaseRequest(
                resource_key=self._resource_key(owner.host_id),
                owner=owner.model_dump_json(),
                ttl_seconds=self._ttl_seconds,
            )
        )
        if lease is None:
            current = await self._store.read(self._resource_key(owner.host_id))
            if current is not None:
                await self._store.release(current)
            lease = await self._store.acquire(
                FencedLeaseRequest(
                    resource_key=self._resource_key(owner.host_id),
                    owner=owner.model_dump_json(),
                    ttl_seconds=self._ttl_seconds,
                )
            )
        if lease is None:
            raise RuntimeError("Codex host presence租约竞争失败。")
        return self._to_presence(lease)

    async def renew(self, presence: CodexHostPresence) -> CodexHostPresence | None:
        renewed = await self._store.renew(
            self._to_lease(presence),
            self._ttl_seconds,
        )
        return None if renewed is None else self._to_presence(renewed)

    async def release(self, presence: CodexHostPresence) -> bool:
        return await self._store.release(self._to_lease(presence))

    async def read(self, host_id: UUID) -> CodexHostPresence | None:
        lease = await self._store.read(self._resource_key(host_id))
        return None if lease is None else self._to_presence(lease)

    async def list_present(self, host_ids: list[UUID]) -> set[UUID]:
        """批量读取仍有新鲜租约的主机集合。"""

        presences = await asyncio.gather(*(self.read(host_id) for host_id in host_ids))
        return {
            host_id
            for host_id, presence in zip(host_ids, presences, strict=True)
            if presence is not None
        }

    def _to_presence(self, lease: FencedLease) -> CodexHostPresence:
        return CodexHostPresence(
            owner=CodexHostPresenceOwner.model_validate_json(lease.owner),
            fencing_token=lease.fencing_token,
            expires_at=lease.expires_at,
        )

    def _to_lease(self, presence: CodexHostPresence) -> FencedLease:
        return FencedLease(
            resource_key=self._resource_key(presence.owner.host_id),
            owner=presence.owner.model_dump_json(),
            fencing_token=presence.fencing_token,
            expires_at=presence.expires_at,
        )

    def _resource_key(self, host_id: UUID) -> str:
        return f"{CODEX_HOST_PRESENCE_NAMESPACE}:{host_id}"
