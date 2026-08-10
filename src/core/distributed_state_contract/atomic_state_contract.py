"""通用有界 TTL 原子状态契约。"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field


class AtomicStateRecord(BaseModel):
    """状态记录公共字段。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(min_length=1, max_length=512)
    value: str = Field(min_length=1, max_length=65_536)
    version: int = Field(ge=1)
    expires_at: datetime | None = None


class AtomicStatePort(Protocol):
    """状态 CAS、写入和删除的最小能力。"""

    async def read(self, key: str) -> AtomicStateRecord | None: ...

    async def create(self, record: AtomicStateRecord) -> bool: ...

    async def create_with_index(
        self,
        *,
        record: AtomicStateRecord,
        index_record: AtomicStateRecord,
    ) -> bool: ...

    async def compare_and_set(
        self,
        *,
        key: str,
        expected_version: int,
        next_value: str,
        expires_at: datetime | None,
    ) -> AtomicStateRecord | None: ...

    async def delete(self, *, key: str, expected_version: int) -> bool: ...
