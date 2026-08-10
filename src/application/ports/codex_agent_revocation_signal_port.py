"""Codex Agent 撤销代次信号端口。"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID


class CodexAgentRevocationSignalPort(Protocol):
    """撤销代次持久化和本实例连接关闭边界。"""

    async def read_generation(self, host_id: UUID) -> int: ...

    async def revoke(self, host_id: UUID) -> int: ...
