"""Agent 重连快照分页与容量降级路径测试。"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import JsonValue

from src.core.codex_contract.app_server_jsonrpc_contract import (
    AppServerMessageTooLargeError,
)
from src.infrastructure.codex_agent.agent_snapshot_builder import AgentSnapshotBuilder
from src.infrastructure.codex_agent.agent_thread_history_capacity_registry import (
    AgentThreadHistoryCapacityRegistry,
)
from src.infrastructure.codex_agent.agent_workspace_registry import (
    AgentWorkspaceDefinition,
    AgentWorkspaceRegistry,
)


class PagingAppServerClient:
    def __init__(self, responses: list[JsonValue | BaseException]) -> None:
        self.responses = responses
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
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def _thread(
    thread_id: str,
    *,
    preview: str = "secret prompt",
    rollout_path: str = "C:\\Users\\ThinkPad\\private\\rollout.jsonl",
) -> dict[str, JsonValue]:
    return {
        "id": thread_id,
        "cwd": "C:\\Users\\ThinkPad\\private",
        "path": rollout_path,
        "preview": preview,
        "name": "Thread title",
        "modelProvider": "openai",
        "status": {"type": "idle"},
        "createdAt": 1,
        "updatedAt": 2,
        "turns": [{"content": "history"}],
    }


@pytest.mark.asyncio
async def test_snapshot_when_thread_list_has_cursor_should_page_and_forward_metadata_only(
    tmp_path: Path,
) -> None:
    rollout = tmp_path / "rollout.jsonl"
    rollout.write_bytes(b"x" * 11)
    first = {
        "data": [
            _thread(
                "thread-1",
                preview="p" * 100_000,
                rollout_path=str(rollout),
            )
        ],
        "nextCursor": "cursor-1",
    }
    second = {"data": [_thread("thread-2")], "nextCursor": None}
    client = PagingAppServerClient([first, second, {"data": [], "nextCursor": None}])
    root = tmp_path / "work"
    root.mkdir()
    registry = AgentWorkspaceRegistry([AgentWorkspaceDefinition("work", "Work", root, False)])
    history_registry = AgentThreadHistoryCapacityRegistry(max_source_bytes=10)

    snapshot = await AgentSnapshotBuilder(
        host_id=uuid4(),
        workspace_registry=registry,
        client=client,  # type: ignore[arg-type]
        app_server_instance_id="instance-1",
        history_capacity_registry=history_registry,
    ).build()

    assert len(client.calls) == 3
    assert client.calls[0][1]["useStateDbOnly"] is True
    assert client.calls[1][1]["cursor"] == "cursor-1"
    assert [thread.thread_id for thread in snapshot.threads] == ["thread-1", "thread-2"]
    assert [thread.display_name for thread in snapshot.threads] == [
        "Thread title",
        "Thread title",
    ]
    assert all(thread.archived is False for thread in snapshot.threads)
    assert history_registry.should_omit("thread-1") is True


@pytest.mark.asyncio
async def test_snapshot_when_workspace_page_exceeds_limit_should_keep_host_available(
    tmp_path: Path,
) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()
    client = PagingAppServerClient(
        [
            AppServerMessageTooLargeError(4 * 1024 * 1024),
            {"data": [_thread("thread-2")], "nextCursor": None},
            {"data": [], "nextCursor": None},
        ]
    )
    registry = AgentWorkspaceRegistry(
        [
            AgentWorkspaceDefinition("first", "First", first_root, False),
            AgentWorkspaceDefinition("second", "Second", second_root, False),
        ]
    )

    snapshot = await AgentSnapshotBuilder(
        host_id=uuid4(),
        workspace_registry=registry,
        client=client,  # type: ignore[arg-type]
        app_server_instance_id="instance-1",
    ).build()

    assert [workspace.key for workspace in snapshot.workspaces] == ["first", "second"]
    assert snapshot.omitted_thread_workspace_keys == ["first"]
    assert [thread.workspace_key for thread in snapshot.threads] == ["second"]
