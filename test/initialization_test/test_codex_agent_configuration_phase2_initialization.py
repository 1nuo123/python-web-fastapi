"""Codex Host Agent 配置初始化测试。"""

from __future__ import annotations

import ssl
from pathlib import Path
from uuid import uuid4

import certifi
import pytest
from pydantic import ValidationError

from src.infrastructure.codex_agent.agent_configuration import (
    MAX_APP_SERVER_LINE_BYTES,
    AgentAppServerSecuritySettings,
    AgentProcessSettings,
    CodexHostAgentSettingsLoader,
    build_agent_tls_context,
)
from src.infrastructure.codex_agent.agent_deployment_profile import AgentDeploymentProfile


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
    assert settings.agent.heartbeat_seconds == 15


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


def test_load_when_development_profile_should_use_its_isolated_default_state(
    tmp_path: Path,
) -> None:
    """配置文件未指定数据库时，development 必须不能回退到生产状态目录。"""

    config = tmp_path / "agent.toml"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config.write_text(
        f"""
[agent]
host_id = "{uuid4()}"
key_id = "{uuid4()}"
display_name = "ThinkPad Development"
deployment_profile = "development"
control_plane_url = "wss://codex-dev.lan/internal/codex-agents/connect"
control_plane_api_url = "https://codex-dev.lan"

[protocol]
agent_schema_version = "2.0"
expected_codex_version = "0.145.*"
app_server_schema_digest = "{"a" * 64}"

[[workspaces]]
key = "work"
display_name = "Work"
root = "{str(workspace).replace(chr(92), chr(92) * 2)}"
""",
        encoding="utf-8",
    )

    settings = CodexHostAgentSettingsLoader(RecordingPermissionVerifier()).load(config)

    assert settings.agent.deployment_profile is AgentDeploymentProfile.DEVELOPMENT
    assert settings.agent.state_database.parent.name == "Development"


def test_development_ca_certificate_should_be_persisted_and_extend_verified_tls(
    tmp_path: Path,
) -> None:
    """开发 CA 只能由开发配置持久化，并保持标准主机名与证书校验。"""

    config = tmp_path / "agent.toml"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    certificate_path = Path(certifi.where()).resolve()
    config.write_text(
        f"""
[agent]
host_id = "{uuid4()}"
key_id = "{uuid4()}"
display_name = "ThinkPad Development"
deployment_profile = "development"
control_plane_url = "wss://codex-dev.lan/internal/codex-agents/connect"
control_plane_api_url = "https://codex-dev.lan"
development_ca_certificate_path = "{str(certificate_path).replace(chr(92), chr(92) * 2)}"

[protocol]
agent_schema_version = "2.0"
expected_codex_version = "0.145.*"
app_server_schema_digest = "{"a" * 64}"

[[workspaces]]
key = "work"
display_name = "Work"
root = "{str(workspace).replace(chr(92), chr(92) * 2)}"
""",
        encoding="utf-8",
    )

    settings = CodexHostAgentSettingsLoader(RecordingPermissionVerifier()).load(config)
    context = build_agent_tls_context(
        deployment_profile=settings.agent.deployment_profile,
        development_ca_certificate_path=settings.agent.development_ca_certificate_path,
    )

    assert settings.agent.development_ca_certificate_path == certificate_path
    assert context is not None
    assert context.verify_mode is ssl.CERT_REQUIRED
    assert context.check_hostname is True


def test_production_settings_should_reject_development_ca_certificate_path() -> None:
    with pytest.raises(ValidationError, match="仅development Agent"):
        AgentProcessSettings.model_validate(
            {
                "host_id": str(uuid4()),
                "key_id": str(uuid4()),
                "display_name": "ThinkPad",
                "control_plane_url": "wss://codex.example/internal/codex-agents/connect",
                "control_plane_api_url": "https://codex.example",
                "development_ca_certificate_path": certifi.where(),
            }
        )


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


def test_process_settings_when_heartbeat_is_not_fifteen_seconds_should_reject() -> None:
    """turn runtime 的固定 watchdog 边界要求 Agent 心跳不能被本地配置漂移。"""

    with pytest.raises(ValidationError):
        AgentProcessSettings.model_validate(
            {
                "host_id": str(uuid4()),
                "key_id": str(uuid4()),
                "display_name": "ThinkPad",
                "control_plane_url": "ws://127.0.0.1:8000/internal/codex-agents/connect",
                "control_plane_api_url": "http://127.0.0.1:8000",
                "heartbeat_seconds": 10,
            }
        )
