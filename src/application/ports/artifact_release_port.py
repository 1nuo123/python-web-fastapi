"""制品发布应用端口。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Protocol

from src.core.artifact_release_contract.artifact_contract import (
    ArtifactActivationRecord,
    ArtifactIdentity,
    ArtifactReleaseEnvelope,
    ArtifactVerificationResult,
)


class ArtifactCatalogPort(Protocol):
    """解析并验证 TUF target。"""

    async def resolve(self, identity: ArtifactIdentity) -> ArtifactReleaseEnvelope: ...


class TufTargetReaderPort(Protocol):
    """读取经过 TUF 验证的通用 target。"""

    async def read_target(self, target_path: str) -> bytes: ...


class ArtifactDownloaderPort(Protocol):
    """受 allowlist 和大小限制的制品下载端口。"""

    async def download(self, envelope: ArtifactReleaseEnvelope, target_url: str) -> bytes: ...


class ArtifactVerifierPort(Protocol):
    """摘要与平台签名验证端口。"""

    async def verify(
        self, envelope: ArtifactReleaseEnvelope, content: bytes
    ) -> ArtifactVerificationResult: ...


class ArtifactStagingPort(Protocol):
    """版本目录暂存和清理端口。"""

    async def stage(self, identity: ArtifactIdentity, content: bytes) -> Path: ...

    async def cleanup(self, identity: ArtifactIdentity) -> None: ...


class ArtifactActivationPort(Protocol):
    """原子激活、提交和回滚端口。"""

    async def activate(
        self, identity: ArtifactIdentity, staged_path: Path
    ) -> ArtifactActivationRecord: ...

    async def commit(self, record: ArtifactActivationRecord) -> ArtifactActivationRecord: ...

    async def rollback(self, record: ArtifactActivationRecord) -> ArtifactActivationRecord: ...


ArtifactHealthCallback = Callable[[ArtifactActivationRecord], Awaitable[bool]]
