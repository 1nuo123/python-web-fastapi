"""python-tuf target 解析适配器。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from urllib.parse import urljoin

from tuf.ngclient import Updater

from src.application.ports.artifact_release_port import ArtifactCatalogPort
from src.core.artifact_release_contract.artifact_contract import (
    ArtifactIdentity,
    ArtifactReleaseEnvelope,
    TufTargetMetadata,
)
from src.core.artifact_release_contract.runtime_contract import ArtifactReleaseRuntimeSettings


class TufArtifactCatalogAdapter(ArtifactCatalogPort):
    """只负责调用 python-tuf，不复制 metadata 状态机。"""

    def __init__(self, *, settings: ArtifactReleaseRuntimeSettings) -> None:
        self._settings = settings

    async def resolve(self, identity: ArtifactIdentity) -> ArtifactReleaseEnvelope:
        return await asyncio.to_thread(self._resolve_sync, identity)

    def _resolve_sync(self, identity: ArtifactIdentity) -> ArtifactReleaseEnvelope:
        updater = Updater(
            metadata_dir=str(Path(self._settings.staging_root) / "tuf" / "metadata"),
            target_dir=str(Path(self._settings.staging_root) / "tuf" / "targets"),
            metadata_base_url=f"{self._settings.repository_url}/metadata/",
            target_base_url=f"{self._settings.repository_url}/targets/",
            bootstrap=Path(self._settings.trusted_root_path).read_bytes(),
        )
        updater.refresh()
        target_path = self._target_path(identity)
        target_info = updater.get_targetinfo(target_path)
        if target_info is None:
            raise FileNotFoundError("TUF未找到目标制品。")
        hashes = {str(key): str(value) for key, value in target_info.hashes.items()}
        custom = {str(key): str(value) for key, value in target_info.custom.items()}
        target = TufTargetMetadata(
            target_path=target_path,
            length=target_info.length,
            hashes=hashes,
            custom=custom,
        )
        return ArtifactReleaseEnvelope(identity=identity, tuf_target=target)

    def _target_path(self, identity: ArtifactIdentity) -> str:
        """将稳定制品身份映射到仓库 target 路径。"""

        return urljoin(
            "targets/",
            "/".join(
                (
                    identity.artifact_name,
                    identity.platform.value,
                    identity.architecture.value,
                    identity.channel.value,
                    identity.version,
                )
            ),
        )
