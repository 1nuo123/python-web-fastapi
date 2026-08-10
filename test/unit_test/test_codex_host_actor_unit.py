"""Codex host 命令 ack/result 关联单元测试。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from src.core.codex_contract.agent_command_contract import AgentCommandJournalState
from src.core.codex_contract.agent_protocol_contract import (
    CodexAgentCommand,
    CodexAgentCommandAck,
    CodexAgentCommandResult,
)
from src.core.codex_contract.connection_session_contract import CodexConnectionFrame
from src.infrastructure.codex.codex_connection_registry import CodexConnectionRegistry
from src.infrastructure.codex.codex_host_actor import CodexHostActor


class SignalingSender:
    def __init__(self) -> None:
        self.frames: list[CodexConnectionFrame] = []
        self.sent = asyncio.Event()

    async def send(self, frame: CodexConnectionFrame) -> None:
        self.frames.append(frame)
        self.sent.set()


@pytest.mark.asyncio
async def test_dispatch_when_agent_ack_is_failed_should_return_structured_result() -> None:
    host_id = uuid4()
    registry = CodexConnectionRegistry(max_connected_agents=1)
    sender = SignalingSender()
    lease = await registry.register(host_id, sender)
    actor = CodexHostActor(host_id=host_id, connection_registry=registry)
    command = CodexAgentCommand(
        command_id=uuid4(),
        operation_id=uuid4(),
        host_id=host_id,
        request_digest="a" * 64,
        command_type="thread.read",
        params={},
        deadline=datetime.now(UTC) + timedelta(seconds=10),
    )
    pending = asyncio.create_task(
        actor.dispatch_and_wait_result(
            command,
            ack_timeout_seconds=1,
            result_timeout_seconds=1,
        )
    )
    await asyncio.wait_for(sender.sent.wait(), timeout=1)
    await actor.accept_ack(
        CodexAgentCommandAck(
            command_id=command.command_id,
            operation_id=command.operation_id,
            state="failed",
            replayed=False,
        )
    )
    expected = CodexAgentCommandResult(
        command_id=command.command_id,
        operation_id=command.operation_id,
        outcome="failed",
        error_code="response_too_large",
    )
    await actor.accept_result(expected)

    try:
        assert await pending == expected
    finally:
        await registry.unregister(lease)


@pytest.mark.asyncio
async def test_dispatch_and_wait_result_accepts_v2_executing_ack() -> None:
    """v2 Agent 将已接收命令编码为 executing 时仍应进入结果等待阶段。"""

    host_id = uuid4()
    registry = CodexConnectionRegistry(max_connected_agents=1)
    sender = SignalingSender()
    lease = await registry.register(host_id, sender)
    actor = CodexHostActor(host_id=host_id, connection_registry=registry)
    command = CodexAgentCommand(
        command_id=uuid4(),
        operation_id=uuid4(),
        host_id=host_id,
        request_digest="b" * 64,
        command_type="thread.read",
        params={},
        deadline=datetime.now(UTC) + timedelta(seconds=10),
    )
    pending = asyncio.create_task(
        actor.dispatch_and_wait_result(
            command,
            ack_timeout_seconds=1,
            result_timeout_seconds=1,
        )
    )
    await asyncio.wait_for(sender.sent.wait(), timeout=1)
    await actor.accept_ack(
        CodexAgentCommandAck(
            command_id=command.command_id,
            operation_id=command.operation_id,
            state=AgentCommandJournalState.EXECUTING,
            replayed=False,
        )
    )
    expected = CodexAgentCommandResult(
        command_id=command.command_id,
        operation_id=command.operation_id,
        outcome="completed",
    )
    await actor.accept_result(expected)

    try:
        assert await pending == expected
    finally:
        await registry.unregister(lease)
