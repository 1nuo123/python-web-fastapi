"""冻结 Agent 注入的 App Server 安全参数契约。"""

from __future__ import annotations

from pathlib import Path

from src.domain.codex.agent_command_policy import AgentCommandPolicy
from src.infrastructure.codex_agent.agent_workspace_registry import (
    AgentWorkspaceDefinition,
    AgentWorkspaceRegistry,
)


def test_thread_start_when_forwarded_should_match_frozen_app_server_security_contract(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    request = AgentCommandPolicy(
        AgentWorkspaceRegistry([AgentWorkspaceDefinition("work", "Work", workspace, True)])
    ).build_request(command_type="thread.start", params={"workspace_key": "work"})

    assert {
        key: request.params[key] for key in ("approvalPolicy", "approvalsReviewer", "sandbox")
    } == {
        "approvalPolicy": "untrusted",
        "approvalsReviewer": "user",
        "sandbox": "workspace-write",
    }
