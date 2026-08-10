"""Codex Host Agent 配置初始化测试。"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.infrastructure.codex_agent.agent_configuration import (
    MAX_APP_SERVER_LINE_BYTES,
    AgentAppServerSecuritySettings,
    AgentProcessSettings,
    CodexHostAgentSettingsLoader,
)


class RecordingPermissionVerifier:
    def __init__(self) -> None:
        self.paths: list[Path] = []

    def verify(self, path: Path) -> None:
        self.paths.append(path)


def test_load_when_valid_should_verify_acl_and_not_require_token_in_toml(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config = tmp_path / "agent.toml"
    config.write_text(
        f"""
[agent]
host_id = "{uuid4()}"
key_id = "{uuid4()}"
display_name = "ThinkPad"
control_plane_url = "wss://codex.example/internal/codex-agents/connect"
control_plane_api_url = "https://codex.example"

[protocol]
agent_schema_version = "2.0"
expected_codex_version = "0.145.*"
app_server_schema_digest = "{"a" * 64}"

[[workspaces]]
key = "work"
display_name = "Work"
root = "{str(workspace).replace(chr(92), chr(92) * 2)}"
allow_write = true
""",
        encoding="utf-8",
    )
    verifier = RecordingPermissionVerifier()
    settings = CodexHostAgentSettingsLoader(verifier).load(config)

    assert verifier.paths == [config]
    assert settings.agent.key_id is not None
    assert settings.agent.legacy_credential_id is None
    assert settings.workspaces[0].root == workspace
    assert settings.app_server_security.approval_policy == "untrusted"
    assert settings.app_server_security.sandbox_mode == "workspace-write"


def test_load_when_workspace_key_duplicates_should_reject(tmp_path: Path) -> None:
    config = tmp_path / "agent.toml"
    root = str(tmp_path).replace("\\", "\\\\")
    config.write_text(
        f"""
[agent]
host_id = "{uuid4()}"
key_id = "{uuid4()}"
display_name = "ThinkPad"
control_plane_url = "ws://127.0.0.1:8000/internal/codex-agents/connect"
control_plane_api_url = "http://127.0.0.1:8000"

[protocol]
agent_schema_version = "2.0"
expected_codex_version = "0.145.*"
app_server_schema_digest = "{"a" * 64}"

[[workspaces]]
key = "same"
display_name = "One"
root = "{root}"

[[workspaces]]
key = "same"
display_name = "Two"
root = "{root}"
""",
        encoding="utf-8",
    )
    with pytest.raises(ValidationError):
        CodexHostAgentSettingsLoader(RecordingPermissionVerifier()).load(config)


def test_security_settings_when_unsafe_value_should_reject() -> None:
    with pytest.raises(ValidationError):
        AgentAppServerSecuritySettings.model_validate({"approval_policy": "never"})


def test_process_settings_when_line_limit_exceeds_four_mib_should_reject() -> None:
    with pytest.raises(ValidationError):
        AgentProcessSettings.model_validate(
            {
                "host_id": str(uuid4()),
                "key_id": str(uuid4()),
                "display_name": "ThinkPad",
                "control_plane_url": "ws://127.0.0.1:8000/internal/codex-agents/connect",
                "control_plane_api_url": "http://127.0.0.1:8000",
                "max_app_server_line_bytes": MAX_APP_SERVER_LINE_BYTES + 1,
            }
        )
