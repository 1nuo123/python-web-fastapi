"""Phase 2 Agent 命令执行、ack 丢失与重放测试。"""

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
from src.core.worktree_contract.worktree_contract import (
    GitWorktreeBindRequest,
    GitWorktreeCreateRequest,
    GitWorktreeListResult,
    GitWorktreeOperationResult,
    GitWorktreeRemoveRequest,
    GitWorktreeSnapshot,
)
from src.domain.codex.agent_command_policy import AgentCommandPolicy, calculate_agent_request_digest
from src.infrastructure.codex_agent.agent_command_executor import AgentCommandExecutor
from src.infrastructure.codex_agent.agent_command_journal import AgentCommandJournal
from src.infrastructure.codex_agent.agent_execution_root_store import AgentExecutionRootStore
from src.infrastructure.codex_agent.agent_thread_history_capacity_registry import (
    AgentThreadHistoryCapacityRegistry,
)
from src.infrastructure.codex_agent.agent_workspace_registry import (
    AgentWorkspaceDefinition,
    AgentWorkspaceRegistry,
)


class RecordingAppServerClient:
    def __init__(self, *, timeout: bool = False) -> None:
        self.calls: list[tuple[str, JsonValue]] = []
        self.timeout = timeout

    async def request(
        self,
        method: str,
        params: JsonValue,
        *,
        timeout_seconds: float,
        operation_id: str | None = None,
    ) -> JsonValue:
        self.calls.append((method, params))
        if self.timeout:
            raise TimeoutError
        return {"thread": {"id": "thread-1"}, "turn": {"id": "turn-1"}}


class RecordingWorktreePort:
    """记录所有 Git worktree 端口调用。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def create(self, request: GitWorktreeCreateRequest) -> GitWorktreeOperationResult:
        self.calls.append(f"create:{request.workspace_key}")
        return GitWorktreeOperationResult(success=False, message="测试不允许创建。")

    def list(self, workspace_key: str) -> GitWorktreeListResult:
        self.calls.append(f"list:{workspace_key}")
        return GitWorktreeListResult(items=())

    def remove(self, request: GitWorktreeRemoveRequest) -> GitWorktreeOperationResult:
        self.calls.append(f"remove:{request.worktree_id}")
        return GitWorktreeOperationResult(success=True)

    def prune(self, workspace_key: str) -> GitWorktreeListResult:
        self.calls.append(f"prune:{workspace_key}")
        return GitWorktreeListResult(items=())

    def find_by_thread(
        self,
        workspace_key: str,
        thread_id: str,
    ) -> GitWorktreeSnapshot | None:
        self.calls.append(f"find:{workspace_key}:{thread_id}")
        return None

    def bind_thread(self, request: GitWorktreeBindRequest) -> GitWorktreeOperationResult:
        self.calls.append(f"bind:{request.worktree_id}")
        return GitWorktreeOperationResult(success=False, message="测试不允许绑定。")


def build_command(host_id, params: dict[str, JsonValue]) -> CodexAgentCommand:
    return CodexAgentCommand(
        command_id=uuid4(),
        operation_id=uuid4(),
        host_id=host_id,
        request_digest=calculate_agent_request_digest("turn.start", params),
        command_type="turn.start",
        params=params,
        deadline=datetime.now(UTC) + timedelta(seconds=10),
    )


@pytest.mark.asyncio
async def test_execute_when_ack_result_replayed_should_not_call_app_server_twice(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    registry = AgentWorkspaceRegistry([AgentWorkspaceDefinition("work", "Work", workspace, True)])
    journal = AgentCommandJournal(tmp_path / "state.sqlite")
    client = RecordingAppServerClient()
    acks: list[CodexAgentCommandAck] = []
    results: list[CodexAgentCommandResult] = []

    async def record_ack(ack: CodexAgentCommandAck) -> None:
        acks.append(ack)

    async def record_result(result: CodexAgentCommandResult) -> None:
        results.append(result)

    executor = AgentCommandExecutor(
        journal=journal,
        client=client,
        command_policy=AgentCommandPolicy(registry),
        ack_sender=record_ack,
        result_sender=record_result,
    )
    params: dict[str, JsonValue] = {
        "workspace_key": "work",
        "threadId": "thread-1",
        "input": [{"type": "text", "text": "hello", "text_elements": []}],
    }
    command = build_command(uuid4(), params)
    try:
        await executor.execute(command)
        await executor.execute(command)
    finally:
        journal.close()

    assert len(client.calls) == 1
    assert [ack.state for ack in acks] == ["accepted", "completed"]
    assert acks[1].replayed is True
    assert [result.outcome for result in results] == ["completed", "completed"]


@pytest.mark.asyncio
async def test_execute_when_rpc_result_unknown_should_leave_executing_and_require_reconciliation(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    registry = AgentWorkspaceRegistry([AgentWorkspaceDefinition("work", "Work", workspace, True)])
    journal = AgentCommandJournal(tmp_path / "state.sqlite")
    client = RecordingAppServerClient(timeout=True)
    acks: list[CodexAgentCommandAck] = []
    results: list[CodexAgentCommandResult] = []

    async def record_ack(ack: CodexAgentCommandAck) -> None:
        acks.append(ack)

    async def record_result(result: CodexAgentCommandResult) -> None:
        results.append(result)

    executor = AgentCommandExecutor(
        journal=journal,
        client=client,
        command_policy=AgentCommandPolicy(registry),
        ack_sender=record_ack,
        result_sender=record_result,
    )
    params: dict[str, JsonValue] = {
        "workspace_key": "work",
        "threadId": "thread-1",
        "input": [{"type": "text", "text": "hello", "text_elements": []}],
    }
    command = build_command(uuid4(), params)
    try:
        await executor.execute(command)
        await executor.execute(command)
    finally:
        journal.close()

    assert len(client.calls) == 1
    assert acks[0].recovery_required is True
    assert [result.outcome for result in results] == ["unknown", "unknown"]


@pytest.mark.asyncio
async def test_execute_when_thread_history_source_is_too_large_should_request_metadata_only(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    rollout = tmp_path / "rollout.jsonl"
    rollout.write_bytes(b"x" * 65)
    registry = AgentWorkspaceRegistry([AgentWorkspaceDefinition("work", "Work", workspace, False)])
    history_registry = AgentThreadHistoryCapacityRegistry(max_source_bytes=64)
    history_registry.register("thread-1", str(rollout))
    journal = AgentCommandJournal(tmp_path / "state.sqlite")
    client = RecordingAppServerClient()
    results: list[CodexAgentCommandResult] = []

    async def ignore_ack(_ack: CodexAgentCommandAck) -> None:
        return

    async def record_result(result: CodexAgentCommandResult) -> None:
        results.append(result)

    executor = AgentCommandExecutor(
        journal=journal,
        client=client,
        command_policy=AgentCommandPolicy(registry),
        ack_sender=ignore_ack,
        result_sender=record_result,
        history_capacity_registry=history_registry,
    )
    params: dict[str, JsonValue] = {
        "workspace_key": "work",
        "threadId": "thread-1",
        "includeTurns": True,
    }
    command = CodexAgentCommand(
        command_id=uuid4(),
        operation_id=uuid4(),
        host_id=uuid4(),
        request_digest=calculate_agent_request_digest("thread.read", params),
        command_type="thread.read",
        params=params,
        deadline=datetime.now(UTC) + timedelta(seconds=10),
    )
    try:
        await executor.execute(command)
    finally:
        journal.close()

    assert client.calls[0][0] == "thread/read"
    assert client.calls[0][1]["includeTurns"] is False
    assert results[0].outcome == "completed"
    assert results[0].result is not None
    assert results[0].result["historyStatus"] == "omitted_too_large"


@pytest.mark.asyncio
async def test_execute_when_workspace_is_not_isolated_should_skip_all_git_calls(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "ordinary-workspace"
    workspace.mkdir()
    registry = AgentWorkspaceRegistry(
        [AgentWorkspaceDefinition("ordinary", "Ordinary", workspace, True)]
    )
    journal = AgentCommandJournal(tmp_path / "state.sqlite")
    execution_root_store = AgentExecutionRootStore(tmp_path / "execution-roots.json")
    worktree_port = RecordingWorktreePort()
    client = RecordingAppServerClient()

    async def ignore_ack(_ack: CodexAgentCommandAck) -> None:
        return

    async def ignore_result(_result: CodexAgentCommandResult) -> None:
        return

    params: dict[str, JsonValue] = {
        "workspace_key": "ordinary",
        "threadId": "thread-1",
        "includeTurns": True,
    }
    command = CodexAgentCommand(
        command_id=uuid4(),
        operation_id=uuid4(),
        host_id=uuid4(),
        request_digest=calculate_agent_request_digest("thread.read", params),
        command_type="thread.read",
        params=params,
        deadline=datetime.now(UTC) + timedelta(seconds=10),
    )
    executor = AgentCommandExecutor(
        journal=journal,
        client=client,
        command_policy=AgentCommandPolicy(registry),
        ack_sender=ignore_ack,
        result_sender=ignore_result,
        worktree_port=worktree_port,
        execution_root_store=execution_root_store,
        workspace_registry=registry,
    )
    try:
        await executor.execute(command)
    finally:
        journal.close()

    assert worktree_port.calls == []
    assert client.calls[0][0] == "thread/read"
    assert "cwd" not in client.calls[0][1]
    assert execution_root_store.require("thread-1").execution_root == workspace
