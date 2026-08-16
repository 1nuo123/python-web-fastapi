"""Windows Agent 已安装版本与在线更新版本选择。"""

from __future__ import annotations

import hashlib
import json
import logging
import sys
from pathlib import Path
from typing import Protocol

from src.core.codex_contract.agent_release_manifest_contract import (
    parse_agent_release_version,
)
from src.infrastructure.artifact_release.signed_activation import (
    ACTIVE_VERSION_FILE_NAME,
    ActiveArtifactVersionRecord,
    load_active_artifact_version,
)
from src.infrastructure.codex_agent.agent_configuration import AgentBootstrapSettings

AGENT_EXECUTABLE_FILE_NAME = "codex-remote-agent.exe"


class AgentExecutableSignatureVerifierPort(Protocol):
    """校验候选 Agent 可执行文件签名。"""

    async def verify(self, path: Path) -> object:
        """校验签名；不可信时抛出异常。"""


class WindowsAgentFileVersionReader:
    """通过 Windows 版本资源读取正式 Agent 三段版本。"""

    def read(self, path: Path) -> str:
        """读取并规范化 ProductVersion。"""

        if sys.platform != "win32":
            raise OSError("Agent Windows文件版本只能在Windows上读取。")
        try:
            import win32api
        except ImportError as exc:
            raise RuntimeError("Windows Agent运行环境缺少pywin32依赖。") from exc

        fixed_info = win32api.GetFileVersionInfo(str(path), "\\")
        major = fixed_info["FileVersionMS"] >> 16
        minor = fixed_info["FileVersionMS"] & 0xFFFF
        patch = fixed_info["FileVersionLS"] >> 16
        revision = fixed_info["FileVersionLS"] & 0xFFFF
        if revision != 0:
            raise ValueError("Agent Windows文件版本必须使用三段版本和零修订号。")
        normalized = f"{major}.{minor}.{patch}"
        parse_agent_release_version(normalized)
        return normalized


class AgentExecutableSelector:
    """只选择版本较新且仍满足本地完整性边界的 Agent。"""

    def __init__(
        self,
        *,
        version_reader: WindowsAgentFileVersionReader,
        signature_verifier: AgentExecutableSignatureVerifierPort | None,
    ) -> None:
        self._version_reader = version_reader
        self._signature_verifier = signature_verifier
        self._logger = logging.getLogger("codex_host_agent")

    async def select(
        self,
        *,
        installed_executable_path: Path,
        releases_root: Path,
        bootstrap: AgentBootstrapSettings,
    ) -> Path:
        """在 MSI 内置版本和已激活在线版本中选择可信的较新版本。"""

        installed_path = installed_executable_path.resolve(strict=True)
        installed_version = self._version_reader.read(installed_path)
        if installed_version != bootstrap.agent_version:
            raise PermissionError("MSI内置Agent版本与bootstrap版本不一致。")
        if bootstrap.release is None or self._signature_verifier is None:
            return installed_path
        await self._signature_verifier.verify(installed_path)
        active_record_path = releases_root.resolve() / ACTIVE_VERSION_FILE_NAME
        if not active_record_path.is_file():
            return installed_path
        try:
            active = self._load_active_release(releases_root)
            if parse_agent_release_version(active.version) <= parse_agent_release_version(
                installed_version
            ):
                return installed_path
            active_path = self._validate_active_path(active, releases_root)
            self._validate_active_digest(active, active_path)
            if self._version_reader.read(active_path) != active.version:
                raise PermissionError("Agent活动版本记录与可执行文件版本不一致。")
            await self._signature_verifier.verify(active_path)
        except (OSError, ValueError, PermissionError):
            self._logger.exception("Agent活动版本校验失败，回退到MSI内置版本。")
            return installed_path
        return active_path

    @staticmethod
    def _load_active_release(releases_root: Path) -> ActiveArtifactVersionRecord:
        active_path = releases_root.resolve() / ACTIVE_VERSION_FILE_NAME
        if not active_path.is_file():
            raise FileNotFoundError("Agent不存在活动在线版本。")
        try:
            return load_active_artifact_version(active_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("Agent活动版本记录无效。") from exc

    @staticmethod
    def _validate_active_path(
        active: ActiveArtifactVersionRecord,
        releases_root: Path,
    ) -> Path:
        from src.core.artifact_release_contract.artifact_contract import (
            ArtifactArchitecture,
            ArtifactChannel,
            ArtifactPlatform,
        )

        if (
            active.artifact_name != AGENT_EXECUTABLE_FILE_NAME
            or active.platform is not ArtifactPlatform.WINDOWS
            or active.architecture is not ArtifactArchitecture.X86_64
            or active.channel is not ArtifactChannel.STABLE
        ):
            raise PermissionError("Agent活动版本身份不符合Windows正式发布契约。")
        root = releases_root.resolve()
        active_path = active.path.resolve(strict=True)
        expected_path = (
            root
            / AGENT_EXECUTABLE_FILE_NAME
            / ArtifactPlatform.WINDOWS.value
            / ArtifactArchitecture.X86_64.value
            / ArtifactChannel.STABLE.value
            / active.version
            / AGENT_EXECUTABLE_FILE_NAME
        ).resolve()
        if active_path != expected_path:
            raise PermissionError("Agent活动版本路径超出受控发布目录。")
        return active_path

    @staticmethod
    def _validate_active_digest(active: ActiveArtifactVersionRecord, path: Path) -> None:
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != active.digest_sha256:
            raise PermissionError("Agent活动版本摘要校验失败。")
