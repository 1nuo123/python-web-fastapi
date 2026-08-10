"""Agent App Server 安全策略异常测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.domain.codex.agent_command_policy import (
    AgentCommandPolicy,
    AgentCommandValidationError,
)
from src.infrastructure.codex_agent.agent_workspace_registry import (
    AgentWorkspaceDefinition,
    AgentWorkspaceRegistry,
)


def test_build_request_when_control_plane_overrides_approval_should_reject(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    policy = AgentCommandPolicy(
        AgentWorkspaceRegistry([AgentWorkspaceDefinition("work", "Work", workspace, True)])
    )

    with pytest.raises(AgentCommandValidationError, match="不得指定"):
        policy.build_request(
            command_type="thread.start",
            params={"workspace_key": "work", "approvalPolicy": "never"},
        )
