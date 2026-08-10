"""应用生命周期内延迟解析通用原子状态。"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from src.core.distributed_state_contract.atomic_state_contract import (
    AtomicStatePort,
    AtomicStateRecord,
)


class DeferredAtomicState(AtomicStatePort):
    """让装配期用例在请求时访问已启动的状态资源。"""

    def __init__(self, *, state_provider: Callable[[], AtomicStatePort]) -> None:
        self._state_provider = state_provider

    async def read(self, key: str) -> AtomicStateRecord | None:
        return await self._state_provider().read(key)

    async def create(self, record: AtomicStateRecord) -> bool:
        return await self._state_provider().create(record)

    async def create_with_index(
        self,
        *,
        record: AtomicStateRecord,
        index_record: AtomicStateRecord,
    ) -> bool:
        return await self._state_provider().create_with_index(
            record=record,
            index_record=index_record,
        )

    async def compare_and_set(
        self,
        *,
        key: str,
        expected_version: int,
        next_value: str,
        expires_at: datetime | None,
    ) -> AtomicStateRecord | None:
        return await self._state_provider().compare_and_set(
            key=key,
            expected_version=expected_version,
            next_value=next_value,
            expires_at=expires_at,
        )

    async def delete(self, *, key: str, expected_version: int) -> bool:
        return await self._state_provider().delete(
            key=key,
            expected_version=expected_version,
        )
