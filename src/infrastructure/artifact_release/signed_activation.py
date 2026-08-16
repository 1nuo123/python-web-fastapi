"""版本 launcher 的原子激活与回滚适配器。"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from src.application.ports.artifact_release_port import ArtifactActivationPort
from src.core.artifact_release_contract.artifact_contract import (
    ArtifactActivationRecord,
    ArtifactActivationState,
    ArtifactArchitecture,
    ArtifactChannel,
    ArtifactIdentity,
    ArtifactPlatform,
)

ACTIVE_VERSION_FILE_NAME = "active-version.json"


class ActiveArtifactVersionRecord(BaseModel):
    """原子 launcher 指针的递归、强类型持久化结构。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_name: str
    platform: ArtifactPlatform
    architecture: ArtifactArchitecture
    channel: ArtifactChannel
    version: str
    digest_sha256: str
    path: Path
    previous: ActiveArtifactVersionRecord | None = None


def load_active_artifact_version(path: Path) -> ActiveArtifactVersionRecord:
    """读取并校验 active-version.json。"""

    return ActiveArtifactVersionRecord.model_validate_json(path.read_text("utf-8"))


class AtomicArtifactActivationAdapter(ArtifactActivationPort):
    """用 active-version.json 原子选择版本并保留上一版本。"""

    def __init__(self, *, root: str | Path) -> None:
        self._root = Path(root)
        self._active_file = self._root / ACTIVE_VERSION_FILE_NAME

    async def activate(
        self, identity: ArtifactIdentity, staged_path: Path
    ) -> ArtifactActivationRecord:
        return await asyncio.to_thread(self._activate_sync, identity, staged_path)

    async def commit(self, record: ArtifactActivationRecord) -> ArtifactActivationRecord:
        return record.model_copy(update={"state": ArtifactActivationState.COMMITTED})

    async def rollback(self, record: ArtifactActivationRecord) -> ArtifactActivationRecord:
        return await asyncio.to_thread(self._rollback_sync, record)

    def _activate_sync(
        self, identity: ArtifactIdentity, staged_path: Path
    ) -> ArtifactActivationRecord:
        self._root.mkdir(parents=True, exist_ok=True)
        previous = (
            load_active_artifact_version(self._active_file) if self._active_file.exists() else None
        )
        payload = ActiveArtifactVersionRecord(
            artifact_name=identity.artifact_name,
            platform=identity.platform,
            architecture=identity.architecture,
            channel=identity.channel,
            version=identity.version,
            digest_sha256=identity.digest_sha256,
            path=staged_path,
            previous=previous,
        )
        temporary = self._active_file.with_suffix(".tmp")
        temporary.write_text(payload.model_dump_json(), "utf-8")
        os.replace(temporary, self._active_file)
        return ArtifactActivationRecord(
            identity=identity,
            state=ArtifactActivationState.ACTIVE,
            staged_path=staged_path,
            activated_at=datetime.now(UTC),
        )

    def _rollback_sync(self, record: ArtifactActivationRecord) -> ArtifactActivationRecord:
        if not self._active_file.exists():
            raise RuntimeError("没有可回滚的激活版本。")
        payload = load_active_artifact_version(self._active_file)
        if payload.previous is None:
            self._active_file.unlink()
        else:
            temporary = self._active_file.with_suffix(".tmp")
            temporary.write_text(payload.previous.model_dump_json(), "utf-8")
            os.replace(temporary, self._active_file)
        return record.model_copy(update={"state": ArtifactActivationState.ROLLED_BACK})
