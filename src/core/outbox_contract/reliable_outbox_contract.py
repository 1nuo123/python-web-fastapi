"""与业务 transport 无关的可靠 Outbox runner 契约。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Generic, Protocol, TypeVar

OutboxRecord = TypeVar("OutboxRecord")


class OutboxDeliveryOutcome(StrEnum):
    """一次 delivery 的稳定结果。"""

    DELIVERED = "delivered"
    DEFERRED = "deferred"
    UNKNOWN = "unknown"
    FAILED_PERMANENT = "failed_permanent"


class ReliableOutboxAdapterPort(Protocol, Generic[OutboxRecord]):
    """业务 adapter 提供 claim、deliver 与失败记录。"""

    def claim(
        self,
        *,
        limit: int,
        stale_before_epoch: int | None,
    ) -> list[OutboxRecord]: ...

    def deliver(self, record: OutboxRecord) -> OutboxDeliveryOutcome: ...

    def record_failure(self, record: OutboxRecord, failure_reason: str) -> None: ...


class AsyncReliableOutboxAdapterPort(Protocol, Generic[OutboxRecord]):
    """异步 transport 使用的同语义 adapter。"""

    async def claim(
        self,
        *,
        limit: int,
        stale_before_epoch: int | None,
    ) -> list[OutboxRecord]: ...

    async def deliver(self, record: OutboxRecord) -> OutboxDeliveryOutcome: ...

    async def record_failure(self, record: OutboxRecord, failure_reason: str) -> None: ...


@dataclass(frozen=True, slots=True)
class ReliableOutboxRunResult:
    """一次重扫结果。"""

    scanned_count: int
    delivered_count: int
    deferred_count: int
    unknown_count: int
    failed_count: int
    permanently_failed_count: int = 0
