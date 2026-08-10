"""Agent 工作区白名单路径与链接逃逸测试。"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from src.infrastructure.codex_agent.agent_workspace_registry import (
    AgentWorkspaceAccessError,
    AgentWorkspaceDefinition,
    AgentWorkspaceRegistry,
)


def test_resolve_path_when_parent_traversal_escapes_root_should_reject(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    registry = AgentWorkspaceRegistry([AgentWorkspaceDefinition("work", "Work", root, True)])

    with pytest.raises(AgentWorkspaceAccessError):
        registry.resolve_path("work", "../outside.txt")


def test_resolve_path_when_link_targets_outside_root_should_reject(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    link = root / "outside-link"
    if os.name == "nt":
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
            check=True,
            capture_output=True,
        )
    else:
        link.symlink_to(outside, target_is_directory=True)
    registry = AgentWorkspaceRegistry([AgentWorkspaceDefinition("work", "Work", root, True)])
    try:
        with pytest.raises(AgentWorkspaceAccessError):
            registry.resolve_path("work", "outside-link/file.txt")
    finally:
        if os.name == "nt" and link.exists():
            os.rmdir(link)


def test_resolve_root_when_write_not_allowed_should_reject(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    registry = AgentWorkspaceRegistry(
        [AgentWorkspaceDefinition("readonly", "Read only", root, False)]
    )

    with pytest.raises(AgentWorkspaceAccessError):
        registry.resolve_root("readonly", require_write=True)
