"""Agent 强制 App Server 安全策略的单元测试。"""

from __future__ import annotations

from pathlib import Path

from src.domain.codex.agent_command_policy import AgentCommandPolicy
from src.infrastructure.codex_agent.agent_workspace_registry import (
    AgentWorkspaceDefinition,
    AgentWorkspaceRegistry,
)


def test_build_request_when_starting_thread_should_inject_local_security_policy(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    policy = AgentCommandPolicy(
        AgentWorkspaceRegistry([AgentWorkspaceDefinition("work", "Work", workspace, True)])
    )

    request = policy.build_request(
        command_type="thread.start",
        params={"workspace_key": "work", "model": "gpt-5"},
    )

    assert request.method == "thread/start"
    assert request.params == {
        "model": "gpt-5",
        "cwd": str(workspace.resolve()),
        "approvalPolicy": "untrusted",
        "approvalsReviewer": "user",
        "sandbox": "workspace-write",
    }
