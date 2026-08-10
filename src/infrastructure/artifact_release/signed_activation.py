"""版本 launcher 的原子激活与回滚适配器。"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from src.application.ports.artifact_release_port import ArtifactActivationPort
from src.core.artifact_release_contract.artifact_contract import (
    ArtifactActivationRecord,
    ArtifactActivationState,
    ArtifactIdentity,
)

ACTIVE_VERSION_FILE_NAME = "active-version.json"


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
        previous = self._active_file.read_text("utf-8") if self._active_file.exists() else None
        payload = {
            "artifact_name": identity.artifact_name,
            "platform": identity.platform.value,
            "architecture": identity.architecture.value,
            "channel": identity.channel.value,
            "version": identity.version,
            "digest_sha256": identity.digest_sha256,
            "path": str(staged_path),
            "previous": previous,
        }
        temporary = self._active_file.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=True, sort_keys=True), "utf-8")
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
        payload = json.loads(self._active_file.read_text("utf-8"))
        previous = payload.get("previous")
        if not isinstance(previous, str) or not previous:
            raise RuntimeError("激活记录缺少上一版本。")
        self._active_file.write_text(previous, "utf-8")
        return record.model_copy(update={"state": ArtifactActivationState.ROLLED_BACK})
