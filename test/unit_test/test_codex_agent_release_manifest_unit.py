"""Codex Agent 发布清单和版本策略单元测试。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import pytest
from pydantic import ValidationError

from src.core.codex_contract.agent_release_manifest_contract import (
    CodexAgentReleaseManifestDetail,
    CodexAgentReleaseManifestEnvelope,
    CodexAgentReleaseManifestHeader,
)
from src.infrastructure.codex_agent.agent_release_runtime import CodexAgentReleaseRuntime
from src.infrastructure.codex_agent.agent_startup_updater import (
    AgentStartupUpdateState,
    AgentVersionPolicy,
    CodexAgentReleaseManifestClient,
    CodexAgentStartupUpdater,
    CodexAgentUpdateHealthCheck,
)

RELEASE_DIGEST = "a" * 64
RELEASE_DOWNLOAD_URL = "https://updates.example.com/agent.exe"
RELEASE_MANIFEST_URL = "https://updates.example.com/manifest.json"
RELEASE_MANIFEST_TARGET_PATH = "codex-agent-release.json"


@dataclass(slots=True)
class StaticManifestClient:
    """Return one already validated release manifest."""

    manifest: CodexAgentReleaseManifestEnvelope

    async def read(self, _target_path: str) -> CodexAgentReleaseManifestEnvelope:
        return self.manifest


@dataclass(slots=True)
class RecordingUpdateCoordinator:
    """Record whether a dynamic security floor forced the update."""

    forced_values: list[bool] = field(default_factory=list)

    async def update_agent(self, **kwargs: object) -> object:
        self.forced_values.append(bool(kwargs["forced"]))

        class SuccessfulResult:
            rollback_performed = False

        return SuccessfulResult()


@dataclass(slots=True)
class StaticReleaseRuntime:
    """Provide only the coordinator surface used by the startup updater."""

    coordinator: RecordingUpdateCoordinator


class TestCodexAgentReleaseManifest:
    """验证版本边界、HTTPS 限制和灰度百分比。"""

    def test_version_policy_should_compare_three_part_versions(self) -> None:
        policy = AgentVersionPolicy()

        assert policy.is_older("1.2.9", "1.3.0") is True
        assert policy.is_older("1.3.0", "1.3.0") is False
        with pytest.raises(ValueError, match="major.minor.patch"):
            policy.is_older("1.3", "1.3.0")

    @pytest.mark.parametrize("rollout_percent", [0, 100])
    def test_manifest_should_accept_rollout_boundaries(self, rollout_percent: int) -> None:
        envelope = CodexAgentReleaseManifestEnvelope(
            header=CodexAgentReleaseManifestHeader(),
            detail=CodexAgentReleaseManifestDetail(
                version="1.2.3",
                digest_sha256=RELEASE_DIGEST,
                download_url=RELEASE_DOWNLOAD_URL,
                rollout_percent=rollout_percent,
                minimum_security_version="1.1.0",
                published_at=datetime.now(UTC),
            ),
        )

        assert envelope.detail.rollout_percent == rollout_percent

    def test_manifest_should_reject_insecure_url_and_unknown_fields(self) -> None:
        with pytest.raises(ValidationError):
            CodexAgentReleaseManifestDetail.model_validate(
                {
                    "version": "1.2.3",
                    "digest_sha256": RELEASE_DIGEST,
                    "download_url": "http://updates.example.com/agent.exe",
                    "rollout_percent": 100,
                    "minimum_security_version": "1.1.0",
                    "published_at": datetime.now(UTC).isoformat(),
                    "unexpected": True,
                }
            )

    def test_manifest_should_reject_security_floor_above_release(self) -> None:
        with pytest.raises(ValidationError, match="最低安全版本"):
            CodexAgentReleaseManifestDetail(
                version="1.2.3",
                digest_sha256=RELEASE_DIGEST,
                download_url=RELEASE_DOWNLOAD_URL,
                rollout_percent=100,
                minimum_security_version="1.2.4",
                published_at=datetime.now(UTC),
            )

    @pytest.mark.asyncio
    async def test_online_security_floor_should_force_update_for_older_agent(self) -> None:
        manifest = CodexAgentReleaseManifestEnvelope(
            header=CodexAgentReleaseManifestHeader(),
            detail=CodexAgentReleaseManifestDetail(
                version="1.3.0",
                digest_sha256=RELEASE_DIGEST,
                download_url=RELEASE_DOWNLOAD_URL,
                rollout_percent=0,
                minimum_security_version="1.2.5",
                published_at=datetime.now(UTC),
            ),
        )
        coordinator = RecordingUpdateCoordinator()
        updater = CodexAgentStartupUpdater(
            runtime=cast(
                CodexAgentReleaseRuntime,
                StaticReleaseRuntime(coordinator=coordinator),
            ),
            manifest_client=cast(
                CodexAgentReleaseManifestClient,
                StaticManifestClient(manifest),
            ),
            version_policy=AgentVersionPolicy(),
        )

        state = await updater.execute(
            manifest_target_path=RELEASE_MANIFEST_TARGET_PATH,
            current_version="1.2.0",
            minimum_security_version="1.1.0",
            host_id=UUID("12345678-1234-5678-1234-567812345678"),
            health_check=cast(CodexAgentUpdateHealthCheck, lambda _record: True),
        )

        assert state is AgentStartupUpdateState.UPDATED
        assert coordinator.forced_values == [True]
