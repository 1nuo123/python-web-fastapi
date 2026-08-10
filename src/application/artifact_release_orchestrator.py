"""可恢复制品发布编排。"""

from __future__ import annotations

from src.application.ports.artifact_release_port import (
    ArtifactActivationPort,
    ArtifactCatalogPort,
    ArtifactDownloaderPort,
    ArtifactHealthCallback,
    ArtifactStagingPort,
    ArtifactVerifierPort,
)
from src.core.artifact_release_contract.artifact_contract import (
    ArtifactIdentity,
    ArtifactReleaseResult,
    ArtifactReleaseStep,
)


class ArtifactReleaseOrchestrator:
    """按 resolve/download/verify/stage/activate/health/commit 顺序发布。"""

    def __init__(
        self,
        *,
        catalog: ArtifactCatalogPort,
        downloader: ArtifactDownloaderPort,
        verifier: ArtifactVerifierPort,
        staging: ArtifactStagingPort,
        activation: ArtifactActivationPort,
    ) -> None:
        self._catalog = catalog
        self._downloader = downloader
        self._verifier = verifier
        self._staging = staging
        self._activation = activation

    async def execute(
        self,
        *,
        identity: ArtifactIdentity,
        target_url: str,
        health_check: ArtifactHealthCallback,
    ) -> ArtifactReleaseResult:
        """执行一次发布；健康门失败时恢复 last-known-good。"""

        completed: list[ArtifactReleaseStep] = []
        envelope = await self._catalog.resolve(identity)
        completed.append(ArtifactReleaseStep.RESOLVE)
        content = await self._downloader.download(envelope, target_url)
        completed.append(ArtifactReleaseStep.DOWNLOAD)
        await self._verifier.verify(envelope, content)
        completed.append(ArtifactReleaseStep.VERIFY)
        staged_path = await self._staging.stage(identity, content)
        completed.append(ArtifactReleaseStep.STAGE)
        record = await self._activation.activate(identity, staged_path)
        completed.append(ArtifactReleaseStep.ACTIVATE)
        if not await health_check(record):
            rolled_back = await self._activation.rollback(record)
            completed.append(ArtifactReleaseStep.ROLLBACK)
            return ArtifactReleaseResult(
                identity=identity,
                completed_steps=tuple(completed),
                activation=rolled_back,
                rollback_performed=True,
                failure_code="artifact.health_failed",
            )
        completed.append(ArtifactReleaseStep.HEALTH)
        committed = await self._activation.commit(record)
        completed.append(ArtifactReleaseStep.COMMIT)
        return ArtifactReleaseResult(
            identity=identity,
            completed_steps=tuple(completed),
            activation=committed,
        )
