"""Agent 超限响应的异常与副作用安全测试。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import JsonValue

from src.core.codex_contract.agent_protocol_contract import (
    CodexAgentCommand,
    CodexAgentCommandAck,
    CodexAgentCommandResult,
)
from src.core.codex_contract.app_server_jsonrpc_contract import (
    AppServerMessageTooLargeError,
)
from src.domain.codex.agent_command_policy import (
    AgentCommandPolicy,
    calculate_agent_request_digest,
)
from src.infrastructure.codex_agent.agent_command_executor import AgentCommandExecutor
from src.infrastructure.codex_agent.agent_command_journal import AgentCommandJournal
from src.infrastructure.codex_agent.agent_workspace_registry import (
    AgentWorkspaceDefinition,
    AgentWorkspaceRegistry,
)


class TooLargeAppServerClient:
    async def request(
        self,
        method: str,
        params: JsonValue,
        *,
        timeout_seconds: float,
        operation_id: str | None = None,
    ) -> JsonValue:
        raise AppServerMessageTooLargeError(4 * 1024 * 1024)


def _command(command_type: str, params: dict[str, JsonValue], host_id) -> CodexAgentCommand:
    return CodexAgentCommand(
        command_id=uuid4(),
        operation_id=uuid4(),
        host_id=host_id,
        request_digest=calculate_agent_request_digest(command_type, params),
        command_type=command_type,
        params=params,
        deadline=datetime.now(UTC) + timedelta(seconds=10),
    )


@pytest.mark.asyncio
async def test_read_command_when_response_is_too_large_should_fail_without_stopping_agent(
    tmp_path: Path,
) -> None:
    root = tmp_path / "work"
    root.mkdir()
    registry = AgentWorkspaceRegistry([AgentWorkspaceDefinition("work", "Work", root, False)])
    journal = AgentCommandJournal(tmp_path / "state.sqlite")
    acks: list[CodexAgentCommandAck] = []
    results: list[CodexAgentCommandResult] = []
    host_id = uuid4()

    async def record_ack(value: CodexAgentCommandAck) -> None:
        acks.append(value)

    async def record_result(value: CodexAgentCommandResult) -> None:
        results.append(value)

    executor = AgentCommandExecutor(
        journal=journal,
        client=TooLargeAppServerClient(),
        command_policy=AgentCommandPolicy(registry),
        ack_sender=record_ack,
        result_sender=record_result,
    )
    try:
        await executor.execute(
            _command("thread.read", {"workspace_key": "work", "threadId": "thread-1"}, host_id)
        )
    finally:
        journal.close()

    assert acks[0].state == "failed"
    assert results[0].error_code == "response_too_large"
    assert results[0].outcome == "failed"


@pytest.mark.asyncio
async def test_write_command_when_response_is_too_large_should_be_unknown_not_failed(
    tmp_path: Path,
) -> None:
    root = tmp_path / "work"
    root.mkdir()
    registry = AgentWorkspaceRegistry([AgentWorkspaceDefinition("work", "Work", root, True)])
    journal = AgentCommandJournal(tmp_path / "state.sqlite")
    results: list[CodexAgentCommandResult] = []
    host_id = uuid4()

    async def ignore_ack(_value: CodexAgentCommandAck) -> None:
        return

    async def record_result(value: CodexAgentCommandResult) -> None:
        results.append(value)

    executor = AgentCommandExecutor(
        journal=journal,
        client=TooLargeAppServerClient(),
        command_policy=AgentCommandPolicy(registry),
        ack_sender=ignore_ack,
        result_sender=record_result,
    )
    try:
        await executor.execute(
            _command(
                "turn.start",
                {"workspace_key": "work", "threadId": "thread-1", "input": []},
                host_id,
            )
        )
    finally:
        journal.close()

    assert results[0].outcome == "unknown"
    assert results[0].error_code == "response_too_large"
