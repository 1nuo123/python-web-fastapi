"""FastAPI 进程内 Agent 长期连接注册表。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from src.core.codex_contract.connection_session_contract import (
    CodexConnectionFrame,
    CodexConnectionProtocolVersion,
    CodexConnectionShutdown,
    CodexHostOfflineError,
    CodexOutboundFrameSenderPort,
)
from src.domain.codex.codex_compatibility_policy import CodexCompatibilityDecision
from src.core.codex_contract.agent_content_contract import AgentContentBudgets


class CodexConnectionCapacityError(ConnectionError):
    """Agent 连接数达到配置上限。"""


@dataclass(frozen=True, slots=True)
class CodexConnectionLease:
    """绑定 host、连接代次与替换停机信号的租约。"""

    host_id: UUID
    epoch: int
    sender: CodexOutboundFrameSenderPort
    shutdown_event: asyncio.Event
    connected_at: datetime
    protocol_version: CodexConnectionProtocolVersion
    compatibility_decision: CodexCompatibilityDecision
    allowed_commands: frozenset[str] | None = None
    history_windows: bool = False
    content_budgets: AgentContentBudgets | None = None
    on_revoke: Callable[[], Awaitable[None]] | None = None
    disconnected: asyncio.Event = field(default_factory=asyncio.Event)

    def close(self, code: int, reason: str) -> None:
        """在同一信号中携带撤销、替换或重启原因。"""
        self.disconnected.set()
        if isinstance(self.shutdown_event, CodexConnectionShutdown):
            self.shutdown_event.request(code, reason)
        else:
            self.shutdown_event.set()


class CodexConnectionRegistry:
    """确保一个 host 仅有一个权威连接，重连会替换旧代次。"""

    def __init__(self, *, max_connected_agents: int) -> None:
        if max_connected_agents <= 0:
            raise ValueError("Agent最大连接数必须大于零。")
        self._max_connected_agents = max_connected_agents
        self._leases: dict[UUID, CodexConnectionLease] = {}
        self._epochs: dict[UUID, int] = {}
        self._lock = asyncio.Lock()
        self._accepting = True

    async def register(
        self,
        host_id: UUID,
        sender: CodexOutboundFrameSenderPort,
        *,
        shutdown_event: asyncio.Event | None = None,
        protocol_version: CodexConnectionProtocolVersion = CodexConnectionProtocolVersion.V1,
        compatibility_decision: CodexCompatibilityDecision = CodexCompatibilityDecision.COMPATIBLE,
        on_revoke: Callable[[], Awaitable[None]] | None = None,
        allowed_commands: frozenset[str] | None = None,
        history_windows: bool = False,
        content_budgets: AgentContentBudgets | None = None,
    ) -> CodexConnectionLease:
        """注册新连接；同 host 重连原子替换并通知旧会话退出。"""

        async with self._lock:
            if not self._accepting:
                raise RuntimeError("Codex连接注册表正在停止。")
            current = self._leases.get(host_id)
            if current is None and len(self._leases) >= self._max_connected_agents:
                raise CodexConnectionCapacityError("Agent连接数已达到上限。")
            epoch = self._epochs.get(host_id, 0) + 1
            self._epochs[host_id] = epoch
            lease = CodexConnectionLease(
                host_id=host_id,
                epoch=epoch,
                sender=sender,
                shutdown_event=shutdown_event or asyncio.Event(),
                connected_at=datetime.now(UTC),
                protocol_version=protocol_version,
                compatibility_decision=compatibility_decision,
                allowed_commands=allowed_commands,
                history_windows=history_windows,
                content_budgets=content_budgets,
                on_revoke=on_revoke,
            )
            self._leases[host_id] = lease
            if current is not None:
                current.close(1008, "connection_replaced")
            return lease

    async def unregister(self, lease: CodexConnectionLease) -> None:
        """只删除仍为当前代次的连接，避免旧会话移除新连接。"""

        lease.disconnected.set()
        async with self._lock:
            current = self._leases.get(lease.host_id)
            if current is not None and current.epoch == lease.epoch:
                self._leases.pop(lease.host_id, None)

    async def send(self, host_id: UUID, frame: CodexConnectionFrame) -> None:
        """向当前权威 Agent 连接有界投递帧。"""

        async with self._lock:
            lease = self._leases.get(host_id)
        if lease is None:
            raise CodexHostOfflineError("Codex主机离线。")
        await lease.sender.send(frame)

    async def read(self, host_id: UUID) -> CodexConnectionLease | None:
        """读取主机当前连接租约。"""

        async with self._lock:
            return self._leases.get(host_id)

    async def list_host_ids(self) -> set[UUID]:
        """读取当前进程内有权威连接租约的 host id 集合。"""

        async with self._lock:
            return set(self._leases)

    async def revoke(self, host_id: UUID) -> None:
        """移除并通知指定主机的当前连接立即退出。"""

        async with self._lock:
            lease = self._leases.pop(host_id, None)
        if lease is not None:
            try:
                if lease.on_revoke is not None:
                    await lease.on_revoke()
            finally:
                lease.close(1008, "device_revoked")

    async def shutdown(self) -> None:
        """停止新注册并通知所有会话排空。"""

        async with self._lock:
            self._accepting = False
            leases = list(self._leases.values())
            self._leases.clear()
        for lease in leases:
            lease.close(1012, "server_restart")
