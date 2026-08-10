"""通用异步 fenced lease 契约。"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field


class FencedLeaseRequest(BaseModel):
    """租约资源、owner 与 TTL。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    resource_key: str = Field(min_length=1, max_length=256)
    owner: str = Field(min_length=1, max_length=256)
    ttl_seconds: int = Field(gt=0, le=86_400)


class FencedLease(BaseModel):
    """带单调 fencing token 的租约。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    resource_key: str
    owner: str
    fencing_token: int = Field(gt=0)
    expires_at: datetime


class FencedLeasePort(Protocol):
    """获取、续租、释放和读取 fenced lease。"""

    async def acquire(self, request: FencedLeaseRequest) -> FencedLease | None: ...

    async def renew(self, lease: FencedLease, ttl_seconds: int) -> FencedLease | None: ...

    async def release(self, lease: FencedLease) -> bool: ...

    async def read(self, resource_key: str) -> FencedLease | None: ...
