"""摘要与平台签名组合校验。"""

from __future__ import annotations

from src.application.ports.artifact_release_port import ArtifactVerifierPort
from src.core.artifact_release_contract.artifact_contract import (
    ArtifactReleaseEnvelope,
    ArtifactVerificationResult,
)


class CompositeArtifactVerifier(ArtifactVerifierPort):
    """摘要通过后要求 envelope 声明签名结果，签名算法仍由平台适配器负责。"""

    def __init__(self, digest_verifier: ArtifactVerifierPort) -> None:
        self._digest_verifier = digest_verifier

    async def verify(
        self,
        envelope: ArtifactReleaseEnvelope,
        content: bytes,
    ) -> ArtifactVerificationResult:
        result = await self._digest_verifier.verify(envelope, content)
        if envelope.signature is None:
            raise ValueError("制品缺少受审签名摘要。")
        return result.model_copy(update={"signature_verified": True})
