"""Agent/Codex 两类 target 的更新协调适配器。"""

from __future__ import annotations

from src.application.artifact_release_orchestrator import ArtifactReleaseOrchestrator
from src.application.ports.artifact_release_port import ArtifactHealthCallback
from src.core.artifact_release_contract.artifact_contract import (
    ArtifactArchitecture,
    ArtifactChannel,
    ArtifactIdentity,
    ArtifactPlatform,
    ArtifactReleaseResult,
)
from src.infrastructure.artifact_release.rollout_policy import ArtifactRolloutPolicy

AGENT_ARTIFACT_NAME = "codex-remote-agent.exe"
CODEX_ARTIFACT_NAME = "codex"


class CodexAgentUpdateCoordinator:
    """只选择业务 target 并委托通用发布编排器。"""

    def __init__(
        self,
        *,
        orchestrator: ArtifactReleaseOrchestrator,
        rollout_policy: ArtifactRolloutPolicy,
    ) -> None:
        self._orchestrator = orchestrator
        self._rollout_policy = rollout_policy

    async def update_agent(
        self,
        *,
        version: str,
        digest_sha256: str,
        target_url: str,
        rollout_percent: int,
        rollout_subject_digest: str,
        forced: bool,
        health_check: ArtifactHealthCallback,
    ) -> ArtifactReleaseResult | None:
        identity = ArtifactIdentity(
            artifact_name=AGENT_ARTIFACT_NAME,
            platform=ArtifactPlatform.WINDOWS,
            architecture=ArtifactArchitecture.X86_64,
            channel=ArtifactChannel.STABLE,
            version=version,
            digest_sha256=digest_sha256,
        )
        if not self._rollout_policy.is_allowed(
            identity=identity,
            rollout_subject_digest=rollout_subject_digest,
            rollout_percent=rollout_percent,
            paused=False,
            forced=forced,
        ):
            return None
        return await self._orchestrator.execute(
            identity=identity,
            target_url=target_url,
            health_check=health_check,
        )

    async def update_codex(
        self,
        *,
        version: str,
        digest_sha256: str,
        target_url: str,
        health_check: ArtifactHealthCallback,
    ) -> ArtifactReleaseResult:
        identity = ArtifactIdentity(
            artifact_name=CODEX_ARTIFACT_NAME,
            platform=ArtifactPlatform.WINDOWS,
            architecture=ArtifactArchitecture.X86_64,
            channel=ArtifactChannel.STABLE,
            version=version,
            digest_sha256=digest_sha256,
        )
        return await self._orchestrator.execute(
            identity=identity,
            target_url=target_url,
            health_check=health_check,
        )
