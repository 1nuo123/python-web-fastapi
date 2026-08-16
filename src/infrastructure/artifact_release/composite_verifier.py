"""摘要与平台签名组合校验。"""

from __future__ import annotations

from src.application.ports.artifact_release_port import ArtifactVerifierPort
from src.core.artifact_release_contract.artifact_contract import (
    ArtifactReleaseEnvelope,
    ArtifactVerificationResult,
)


class CompositeArtifactVerifier(ArtifactVerifierPort):
    """按摘要、TUF 结果和平台签名顺序执行组合校验。"""

    def __init__(
        self,
        digest_verifier: ArtifactVerifierPort,
        signature_verifier: ArtifactVerifierPort,
    ) -> None:
        self._digest_verifier = digest_verifier
        self._signature_verifier = signature_verifier

    async def verify(
        self,
        envelope: ArtifactReleaseEnvelope,
        content: bytes,
    ) -> ArtifactVerificationResult:
        result = await self._digest_verifier.verify(envelope, content)
        if envelope.tuf_target is None:
            raise ValueError("制品缺少已经验证的TUF target元数据。")
        signature_result = await self._signature_verifier.verify(envelope, content)
        return result.model_copy(
            update={
                "signature_verified": signature_result.signature_verified,
                "signature": signature_result.signature,
            }
        )
