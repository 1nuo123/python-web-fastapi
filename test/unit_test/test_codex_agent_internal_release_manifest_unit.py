"""Codex Agent 内部体验发布清单单元测试。"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.cli.build_codex_agent_internal_release_manifest import (
    AgentInternalReleaseManifestBuildCommand,
    CodexAgentInternalReleaseManifestBuilder,
)
from src.core.codex_contract.agent_release_manifest_contract import (
    CodexAgentInternalReleaseManifestEnvelope,
)

INTERNAL_RELEASE_URL = (
    "https://github.com/acme/codex-agent/releases/download/v0.1.16/CodexRemoteAgent.msi"
)


def test_internal_release_manifest_when_msi_exists_should_bind_exact_sha256(tmp_path: Path) -> None:
    installer = tmp_path / "CodexRemoteAgent.msi"
    installer.write_bytes(b"internal-agent-msi")
    output = tmp_path / "internal-release.json"

    manifest = CodexAgentInternalReleaseManifestBuilder().build(
        AgentInternalReleaseManifestBuildCommand(
            installer=installer,
            output=output,
            version="0.1.16",
            download_url=INTERNAL_RELEASE_URL,
        )
    )

    serialized = CodexAgentInternalReleaseManifestEnvelope.model_validate_json(
        output.read_text("utf-8")
    )
    expected_digest = hashlib.sha256(b"internal-agent-msi").hexdigest()
    assert manifest.detail.artifact_sha256 == expected_digest
    assert serialized.detail.artifact_sha256 == expected_digest
    assert serialized.detail.automatic_updates_enabled is False
    assert serialized.detail.download_url == INTERNAL_RELEASE_URL


@pytest.mark.parametrize(
    "download_url",
    [
        "https://github.com/acme/codex-agent/raw/master/CodexRemoteAgent.msi",
        "https://github.com/acme/codex-agent/releases/download/v0.1.16/CodexRemoteAgent.msi?source=web",
        "http://github.com/acme/codex-agent/releases/download/v0.1.16/CodexRemoteAgent.msi",
    ],
)
def test_internal_release_manifest_when_url_is_not_immutable_should_reject(
    tmp_path: Path,
    download_url: str,
) -> None:
    installer = tmp_path / "CodexRemoteAgent.msi"
    installer.write_bytes(b"internal-agent-msi")

    with pytest.raises(ValidationError):
        CodexAgentInternalReleaseManifestBuilder().build(
            AgentInternalReleaseManifestBuildCommand(
                installer=installer,
                output=tmp_path / "internal-release.json",
                version="0.1.16",
                download_url=download_url,
            )
        )
