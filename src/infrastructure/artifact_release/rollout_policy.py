"""按稳定身份执行确定性灰度分桶。"""

from __future__ import annotations

import hashlib

from src.core.artifact_release_contract.artifact_contract import ArtifactChannel, ArtifactIdentity

ROLLOUT_BUCKET_COUNT = 100


class ArtifactRolloutPolicy:
    """不使用用户或主机明文标识的稳定 rollout 决策。"""

    def is_allowed(
        self,
        *,
        identity: ArtifactIdentity,
        rollout_subject_digest: str,
        rollout_percent: int,
        paused: bool,
        forced: bool,
    ) -> bool:
        if paused:
            return False
        if (
            forced
            or identity.channel == ArtifactChannel.STABLE
            and rollout_percent >= ROLLOUT_BUCKET_COUNT
        ):
            return True
        if rollout_percent <= 0:
            return False
        bucket = (
            int(
                hashlib.sha256(
                    f"{rollout_subject_digest}:{identity.artifact_name}:{identity.channel.value}".encode()
                ).hexdigest()[:8],
                16,
            )
            % ROLLOUT_BUCKET_COUNT
        )
        return bucket < rollout_percent
