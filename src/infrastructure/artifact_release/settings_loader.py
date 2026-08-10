"""制品发布 TOML 配置加载器。"""

from __future__ import annotations

import tomllib
from pathlib import Path

from src.core.artifact_release_contract.runtime_contract import ArtifactReleaseRuntimeSettings

ARTIFACT_RELEASE_RUNTIME_SECTION = "runtime"


class ArtifactReleaseSettingsLoader:
    """读取独立 Agent 运行时的强类型制品配置。"""

    def load(self, path: str | Path) -> ArtifactReleaseRuntimeSettings:
        with Path(path).open("rb") as stream:
            payload = tomllib.load(stream)
        section = payload.get(ARTIFACT_RELEASE_RUNTIME_SECTION)
        if not isinstance(section, dict):
            raise ValueError("制品发布配置缺少runtime节。")
        return ArtifactReleaseRuntimeSettings.model_validate(section)
