"""Agent 一次性连接票据提供端口。"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from src.core.codex_contract.device_key_contract import AgentConnectionTicketResponse


class AgentConnectionTicketProviderPort(Protocol):
    """使用设备签名证明换取一次性 WSS 票据。"""

    async def issue(self, *, host_id: UUID, key_id: UUID) -> AgentConnectionTicketResponse: ...
