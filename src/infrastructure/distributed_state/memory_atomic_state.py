"""协议无关的内存原子状态测试实现。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from src.core.distributed_state_contract.atomic_state_contract import (
    AtomicStatePort,
    AtomicStateRecord,
)


class MemoryAtomicState(AtomicStatePort):
    """用于契约测试和本地运行的单进程 CAS 状态。"""

    def __init__(self) -> None:
        self._records: dict[str, AtomicStateRecord] = {}
        self._lock = asyncio.Lock()

    async def read(self, key: str) -> AtomicStateRecord | None:
        async with self._lock:
            record = self._records.get(key)
            if (
                record is not None
                and record.expires_at is not None
                and record.expires_at <= datetime.now(UTC)
            ):
                self._records.pop(key, None)
                return None
            return record

    async def create(self, record: AtomicStateRecord) -> bool:
        async with self._lock:
            current = self._records.get(record.key)
            if (
                current is not None
                and current.expires_at is not None
                and current.expires_at <= datetime.now(UTC)
            ):
                self._records.pop(record.key, None)
                current = None
            if current is not None:
                return False
            self._records[record.key] = record
            return True

    async def create_with_index(
        self,
        *,
        record: AtomicStateRecord,
        index_record: AtomicStateRecord,
    ) -> bool:
        """在同一锁内同时创建主记录和唯一索引。"""

        async with self._lock:
            now = datetime.now(UTC)
            for key in (record.key, index_record.key):
                current = self._records.get(key)
                if (
                    current is not None
                    and current.expires_at is not None
                    and current.expires_at <= now
                ):
                    self._records.pop(key, None)
            if record.key in self._records or index_record.key in self._records:
                return False
            self._records[record.key] = record
            self._records[index_record.key] = index_record
            return True

    async def compare_and_set(
        self,
        *,
        key: str,
        expected_version: int,
        next_value: str,
        expires_at: datetime | None,
    ) -> AtomicStateRecord | None:
        async with self._lock:
            current = self._records.get(key)
            if current is None or current.version != expected_version:
                return None
            next_record = AtomicStateRecord(
                key=key,
                value=next_value,
                version=expected_version + 1,
                expires_at=expires_at,
            )
            self._records[key] = next_record
            return next_record

    async def delete(self, *, key: str, expected_version: int) -> bool:
        async with self._lock:
            current = self._records.get(key)
            if current is None or current.version != expected_version:
                return False
            self._records.pop(key, None)
            return True
