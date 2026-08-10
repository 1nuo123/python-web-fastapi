"""制品 SHA-256 摘要校验适配器。"""

from __future__ import annotations

import asyncio
import hashlib

from src.application.ports.artifact_release_port import ArtifactVerifierPort
from src.core.artifact_release_contract.artifact_contract import (
    ArtifactReleaseEnvelope,
    ArtifactVerificationResult,
)


class Sha256ArtifactVerifier(ArtifactVerifierPort):
    """只使用标准库 hashlib，不实现密码原语。"""

    async def verify(
        self,
        envelope: ArtifactReleaseEnvelope,
        content: bytes,
    ) -> ArtifactVerificationResult:
        return await asyncio.to_thread(self._verify_sync, envelope, content)

    def _verify_sync(
        self,
        envelope: ArtifactReleaseEnvelope,
        content: bytes,
    ) -> ArtifactVerificationResult:
        digest = hashlib.sha256(content).hexdigest()
        if digest != envelope.identity.digest_sha256:
            raise ValueError("制品 SHA-256 摘要校验失败。")
        if envelope.tuf_target is not None:
            expected = envelope.tuf_target.hashes.get("sha256")
            if expected is not None and expected != digest:
                raise ValueError("制品摘要与 TUF sha256 不一致。")
        return ArtifactVerificationResult(
            identity=envelope.identity,
            digest_verified=True,
            signature_verified=envelope.signature is not None,
            signature=envelope.signature,
        )
