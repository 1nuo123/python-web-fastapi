"""Agent 当前可执行文件版本解析。"""

from __future__ import annotations

import hashlib
from pathlib import Path

from src.infrastructure.artifact_release.signed_activation import (
    ACTIVE_VERSION_FILE_NAME,
    load_active_artifact_version,
)

AGENT_EXECUTABLE_FILE_NAME = "codex-remote-agent.exe"


class AgentRuntimeVersionResolver:
    """只信任 managed releases 目录中与当前进程匹配的激活记录。"""

    def __init__(self, *, releases_root: Path) -> None:
        self._releases_root = releases_root.resolve()

    def resolve(self, *, installed_version: str, executable_path: Path) -> str:
        """返回当前进程真实版本；MSI 内置版本回退到 bootstrap。"""

        active_file = self._releases_root / ACTIVE_VERSION_FILE_NAME
        if not active_file.is_file():
            return installed_version
        active = load_active_artifact_version(active_file)
        active_path = active.path.resolve(strict=True)
        if (
            active_path.name.lower() != AGENT_EXECUTABLE_FILE_NAME
            or self._releases_root not in active_path.parents
        ):
            raise PermissionError("Agent激活版本路径超出受控发布目录。")
        if executable_path.resolve() == active_path:
            with active_path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            if digest != active.digest_sha256:
                raise PermissionError("Agent激活版本摘要与活动记录不一致。")
            return active.version
        return installed_version
