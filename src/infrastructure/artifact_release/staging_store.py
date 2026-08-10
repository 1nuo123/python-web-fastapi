"""版本目录暂存适配器。"""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from pathlib import Path

from src.application.ports.artifact_release_port import ArtifactStagingPort
from src.core.artifact_release_contract.artifact_contract import ArtifactIdentity


class LocalArtifactStagingStore(ArtifactStagingPort):
    """在版本目录外写入临时文件后原子改名。"""

    def __init__(self, *, staging_root: str | Path) -> None:
        self._root = Path(staging_root)

    async def stage(self, identity: ArtifactIdentity, content: bytes) -> Path:
        return await asyncio.to_thread(self._stage_sync, identity, content)

    async def cleanup(self, identity: ArtifactIdentity) -> None:
        await asyncio.to_thread(shutil.rmtree, self._version_root(identity), True)

    def _stage_sync(self, identity: ArtifactIdentity, content: bytes) -> Path:
        version_root = self._version_root(identity)
        version_root.parent.mkdir(parents=True, exist_ok=True)
        temporary_root = Path(tempfile.mkdtemp(prefix="stage-", dir=version_root.parent))
        try:
            artifact_path = temporary_root / identity.artifact_name
            with artifact_path.open("wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            if version_root.exists():
                shutil.rmtree(version_root)
            os.replace(temporary_root, version_root)
            return version_root / identity.artifact_name
        except BaseException:
            shutil.rmtree(temporary_root, ignore_errors=True)
            raise

    def _version_root(self, identity: ArtifactIdentity) -> Path:
        return (
            self._root
            / identity.artifact_name
            / identity.platform.value
            / identity.architecture.value
            / identity.channel.value
            / identity.version
        )
