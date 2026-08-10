"""Agent App Server 安全策略的关键路径测试。"""

from __future__ import annotations

from pathlib import Path

from src.domain.codex.agent_command_policy import AgentCommandPolicy
from src.infrastructure.codex_agent.agent_workspace_registry import (
    AgentWorkspaceDefinition,
    AgentWorkspaceRegistry,
)


def test_build_request_when_resuming_and_starting_turn_should_preserve_approval_policy(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    policy = AgentCommandPolicy(
        AgentWorkspaceRegistry([AgentWorkspaceDefinition("work", "Work", workspace, True)])
    )

    resumed = policy.build_request(
        command_type="thread.resume",
        params={"workspace_key": "work", "threadId": "thread-1"},
    )
    started = policy.build_request(
        command_type="turn.start",
        params={
            "workspace_key": "work",
            "threadId": "thread-1",
            "input": [{"type": "text", "text": "hello", "text_elements": []}],
        },
    )

    assert resumed.params["sandbox"] == "workspace-write"
    assert resumed.params["approvalPolicy"] == "untrusted"
    assert started.params["approvalPolicy"] == "untrusted"
    assert started.params["approvalsReviewer"] == "user"
    assert "sandboxPolicy" not in started.params
