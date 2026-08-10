"""Agent 到 App Server 安全参数接口测试。"""

from __future__ import annotations

from pathlib import Path

from src.domain.codex.agent_command_policy import AgentCommandPolicy, AppServerCommandRequest
from src.infrastructure.codex_agent.agent_workspace_registry import (
    AgentWorkspaceDefinition,
    AgentWorkspaceRegistry,
)


def test_build_request_when_turn_starts_should_expose_only_app_server_security_fields(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    request = AgentCommandPolicy(
        AgentWorkspaceRegistry([AgentWorkspaceDefinition("work", "Work", workspace, True)])
    ).build_request(
        command_type="turn.start",
        params={
            "workspace_key": "work",
            "threadId": "thread-1",
            "input": [{"type": "text", "text": "hello", "text_elements": []}],
        },
    )

    assert isinstance(request, AppServerCommandRequest)
    assert request.method == "turn/start"
    assert request.params["approvalPolicy"] == "untrusted"
    assert request.params["approvalsReviewer"] == "user"
    assert "workspace_key" not in request.params
