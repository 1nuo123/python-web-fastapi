"""Agent 命令执行与本地安全策略集成测试。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import JsonValue

from src.core.codex_contract.agent_protocol_contract import CodexAgentCommand
from src.domain.codex.agent_command_policy import AgentCommandPolicy, calculate_agent_request_digest
from src.infrastructure.codex_agent.agent_command_executor import AgentCommandExecutor
from src.infrastructure.codex_agent.agent_command_journal import AgentCommandJournal
from src.infrastructure.codex_agent.agent_workspace_registry import (
    AgentWorkspaceDefinition,
    AgentWorkspaceRegistry,
)


class RecordingAppServerClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, JsonValue]] = []

    async def request(
        self,
        method: str,
        params: JsonValue,
        *,
        timeout_seconds: float,
        operation_id: str | None = None,
    ) -> JsonValue:
        self.calls.append((method, params))
        return {"thread": {"id": "thread-1"}}


@pytest.mark.asyncio
async def test_execute_when_starting_thread_should_forward_local_security_policy(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    journal = AgentCommandJournal(tmp_path / "state.sqlite")
    client = RecordingAppServerClient()
    params: dict[str, JsonValue] = {"workspace_key": "work"}
    command = CodexAgentCommand(
        command_id=uuid4(),
        operation_id=uuid4(),
        host_id=uuid4(),
        request_digest=calculate_agent_request_digest("thread.start", params),
        command_type="thread.start",
        params=params,
        deadline=datetime.now(UTC) + timedelta(seconds=10),
    )

    async def record_ack(_: object) -> None:
        return None

    async def record_result(_: object) -> None:
        return None

    executor = AgentCommandExecutor(
        journal=journal,
        client=client,
        command_policy=AgentCommandPolicy(
            AgentWorkspaceRegistry([AgentWorkspaceDefinition("work", "Work", workspace, True)])
        ),
        ack_sender=record_ack,
        result_sender=record_result,
    )
    try:
        await executor.execute(command)
    finally:
        journal.close()

    assert client.calls[0][0] == "thread/start"
    forwarded = client.calls[0][1]
    assert isinstance(forwarded, dict)
    assert forwarded["approvalPolicy"] == "untrusted"
    assert forwarded["sandbox"] == "workspace-write"
