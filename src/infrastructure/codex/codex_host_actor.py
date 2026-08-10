"""单个 Codex host 的命令关联 actor。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Final
from uuid import UUID, uuid4

from src.core.codex_contract.agent_command_contract import AgentCommandJournalState
from src.core.codex_contract.agent_protocol_contract import (
    CodexAgentCommand,
    CodexAgentCommandAck,
    CodexAgentCommandResult,
)
from src.core.codex_contract.connection_session_contract import (
    CodexConnectionProtocolVersion,
    CodexHostOfflineError,
)
from src.domain.codex.codex_compatibility_policy import CodexCompatibilityDecision
from src.infrastructure.codex.agent_protocol_codec import (
    AgentCommandV2Mapper,
    AgentProtocolCodecRegistry,
    AgentV1MessageType,
)
from src.infrastructure.codex.codex_connection_registry import CodexConnectionRegistry

AGENT_ACK_ACCEPTED_STATES: Final[frozenset[AgentCommandJournalState]] = frozenset(
    {
        AgentCommandJournalState.RECEIVED,
        AgentCommandJournalState.EXECUTING,
        AgentCommandJournalState.ACCEPTED,
        AgentCommandJournalState.COMPLETED,
        AgentCommandJournalState.FAILED,
    }
)


@dataclass(frozen=True, slots=True)
class CodexAcceptedOperation:
    """Agent 已接受或重放的 operation 状态。"""

    ack: CodexAgentCommandAck
    result: CodexAgentCommandResult | None = None


class CodexHostActor:
    """串联 command 投递与异步 ack/result，断线时保留原 command id。"""

    def __init__(self, *, host_id: UUID, connection_registry: CodexConnectionRegistry) -> None:
        self._host_id = host_id
        self._connection_registry = connection_registry
        self._codec_registry = AgentProtocolCodecRegistry()
        self._command_mapper = AgentCommandV2Mapper()
        self._pending_acks: dict[UUID, asyncio.Future[CodexAgentCommandAck]] = {}
        self._pending_results: dict[UUID, asyncio.Future[CodexAgentCommandResult]] = {}

    async def dispatch(
        self,
        command: CodexAgentCommand,
        *,
        ack_timeout_seconds: float,
    ) -> CodexAcceptedOperation:
        """投递稳定命令并只等待 Agent/App Server 接受确认。"""

        if command.command_id in self._pending_acks:
            raise RuntimeError("同一command_id正在等待Agent确认。")
        future = asyncio.get_running_loop().create_future()
        self._pending_acks[command.command_id] = future
        try:
            lease = await self._connection_registry.read(self._host_id)
            if lease is None:
                raise CodexHostOfflineError("Codex主机离线。")
            if (
                lease.compatibility_decision == CodexCompatibilityDecision.READ_ONLY
                and command.command_type not in {"thread.list", "thread.read"}
            ):
                raise PermissionError("当前App Server schema只允许只读命令。")
            if lease.protocol_version == CodexConnectionProtocolVersion.V2:
                frame = self._codec_registry.encode_v2(
                    host_id=self._host_id,
                    message_id=uuid4(),
                    detail=self._command_mapper.from_v1_command(command),
                )
            else:
                frame = self._codec_registry.encode_v1(
                    AgentV1MessageType.COMMAND,
                    command,
                )
            await lease.sender.send(frame)
            ack = await asyncio.wait_for(future, timeout=ack_timeout_seconds)
            return CodexAcceptedOperation(ack=ack)
        finally:
            self._pending_acks.pop(command.command_id, None)

    async def dispatch_and_wait_result(
        self,
        command: CodexAgentCommand,
        *,
        ack_timeout_seconds: float,
        result_timeout_seconds: float,
    ) -> CodexAgentCommandResult:
        """先等待接受确认，再等待同一 command id 的最终查询结果。"""

        if command.command_id in self._pending_results:
            raise RuntimeError("同一command_id正在等待Agent结果。")
        result_future = asyncio.get_running_loop().create_future()
        self._pending_results[command.command_id] = result_future
        try:
            accepted = await self.dispatch(
                command,
                ack_timeout_seconds=ack_timeout_seconds,
            )
            try:
                ack_state = AgentCommandJournalState(accepted.ack.state)
            except ValueError:
                ack_state = AgentCommandJournalState.UNKNOWN
            if ack_state not in AGENT_ACK_ACCEPTED_STATES:
                raise RuntimeError("Agent未确认Codex查询命令。")
            return await asyncio.wait_for(result_future, timeout=result_timeout_seconds)
        finally:
            self._pending_results.pop(command.command_id, None)

    async def accept_ack(self, ack: CodexAgentCommandAck) -> None:
        """完成对应命令的 ack future；迟到 ack 留给 operation reconciliation。"""

        future = self._pending_acks.get(ack.command_id)
        if future is not None and not future.done():
            future.set_result(ack)

    async def accept_result(self, result: CodexAgentCommandResult) -> None:
        """缓存可能先于 ack 到达的结果。"""

        future = self._pending_results.get(result.command_id)
        if future is not None and not future.done():
            future.set_result(result)


class CodexHostActorRegistry:
    """按 host id 稳定复用命令 actor。"""

    def __init__(self, connection_registry: CodexConnectionRegistry) -> None:
        self._connection_registry = connection_registry
        self._actors: dict[UUID, CodexHostActor] = {}

    def get(self, host_id: UUID) -> CodexHostActor:
        """读取或创建单 host actor。"""

        actor = self._actors.get(host_id)
        if actor is None:
            actor = CodexHostActor(host_id=host_id, connection_registry=self._connection_registry)
            self._actors[host_id] = actor
        return actor
