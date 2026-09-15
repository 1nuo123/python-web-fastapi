"""Synchronize runtime download metadata from a built internal release manifest."""

from __future__ import annotations

import argparse
import re
from collections.abc import Sequence
from pathlib import Path

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

from src.core.codex_contract.agent_release_manifest_contract import (
    CodexAgentInternalReleaseManifestEnvelope,
)

_RUNTIME_HEADER = "[runtime]"
_RELEASE_KEYS = frozenset(
    {
        "agent_release_version",
        "agent_release_distribution_mode",
        "agent_release_artifact_sha256",
        "agent_release_download_url",
        "agent_release_manifest_url",
        "agent_release_minimum_security_version",
        "agent_release_source_repository",
        "agent_release_source_revision",
        "agent_release_source_dirty",
    }
)
_REQUIRED_RUNTIME_RELEASE_KEYS = _RELEASE_KEYS - {
    "agent_release_source_repository",
    "agent_release_source_revision",
    "agent_release_source_dirty",
}
_ASSIGNMENT = re.compile(r"^(?P<indent>\s*)(?P<key>[a-z_]+)\s*=.*$")


class InternalReleaseMetadataSyncCommand(BaseModel):
    """Explicit release source and runtime TOML targets."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    manifest: Path
    configs: tuple[Path, ...] = Field(min_length=1)
    minimum_security_version: str | None = None
    dry_run: bool = False


class CodexAgentInternalReleaseMetadataSynchronizer:
    """Updates only existing ``[runtime]`` release keys from one manifest."""

    def synchronize(self, command: InternalReleaseMetadataSyncCommand) -> None:
        manifest = CodexAgentInternalReleaseManifestEnvelope.model_validate_json(
            command.manifest.read_text(encoding="utf-8")
        )
        detail = manifest.detail
        if (
            detail.source_repository is None
            or detail.source_revision is None
            or detail.source_dirty is None
        ):
            raise ValueError("内部发布清单缺少构建来源信息，不能同步到运行时配置。")
        values: dict[str, str] = {
            "agent_release_version": self._toml_string(detail.version),
            "agent_release_distribution_mode": self._toml_string("internal"),
            "agent_release_artifact_sha256": self._toml_string(detail.artifact_sha256),
            "agent_release_download_url": self._toml_string(detail.download_url),
            "agent_release_manifest_url": self._toml_string(
                self._manifest_download_url(detail.download_url)
            ),
            "agent_release_minimum_security_version": self._toml_string(
                command.minimum_security_version or detail.version
            ),
            "agent_release_source_repository": self._toml_string(detail.source_repository),
            "agent_release_source_revision": self._toml_string(detail.source_revision),
            "agent_release_source_dirty": self._toml_bool(detail.source_dirty),
        }
        for config in command.configs:
            updated = self._update_config(config, values)
            if not command.dry_run:
                temporary_path = config.with_suffix(f"{config.suffix}.tmp")
                temporary_path.write_text(updated, encoding="utf-8", newline="")
                temporary_path.replace(config)
            logger.info("Codex Agent内部发布元数据已{}：{}", "校验" if command.dry_run else "同步", config)

    @staticmethod
    def _manifest_download_url(installer_url: str) -> str:
        suffix = "/CodexRemoteAgent.msi"
        if not installer_url.endswith(suffix):
            raise ValueError("内部发布下载地址必须以 CodexRemoteAgent.msi 结尾。")
        return f"{installer_url.removesuffix(suffix)}/internal-release.json"

    def _update_config(self, config: Path, values: dict[str, str]) -> str:
        if not config.is_file():
            raise FileNotFoundError(f"运行时配置不存在：{config}")
        content = config.read_text(encoding="utf-8")
        lines = content.splitlines(keepends=True)
        in_runtime = False
        seen: set[str] = set()
        output: list[str] = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                in_runtime = stripped == _RUNTIME_HEADER
            if in_runtime:
                match = _ASSIGNMENT.match(line)
                if match is not None and match.group("key") in _RELEASE_KEYS:
                    key = match.group("key")
                    if key in seen:
                        raise ValueError(f"运行时配置包含重复发布键：{config} {key}")
                    seen.add(key)
                    newline = "\r\n" if line.endswith("\r\n") else "\n"
                    output.append(f"{match.group('indent')}{key} = {values[key]}{newline}")
                    continue
            output.append(line)
        missing_required = _REQUIRED_RUNTIME_RELEASE_KEYS - seen
        if missing_required:
            missing_keys = ", ".join(sorted(missing_required))
            raise ValueError(f"运行时配置缺少发布键：{config} {missing_keys}")
        missing_provenance = _RELEASE_KEYS - seen
        if missing_provenance:
            if not in_runtime:
                raise ValueError(f"运行时配置不能安全追加构建来源字段：{config}")
            newline = "\r\n" if content.endswith("\r\n") else "\n"
            if output and not output[-1].endswith(("\r\n", "\n")):
                output[-1] += newline
            output.extend(f"{key} = {values[key]}{newline}" for key in sorted(missing_provenance))
        return "".join(output)

    @staticmethod
    def _toml_string(value: str) -> str:
        return f'"{value.replace(chr(34), chr(92) + chr(34))}"'

    @staticmethod
    def _toml_bool(value: bool) -> str:
        return "true" if value else "false"


class CodexAgentInternalReleaseMetadataSyncCli:
    """Command-line entry point used after an immutable internal release build."""

    def execute(self, argv: Sequence[str] | None = None) -> int:
        parser = argparse.ArgumentParser(description="同步 Codex Agent内部发布运行时元数据")
        parser.add_argument("--manifest", required=True, type=Path)
        parser.add_argument("--config", required=True, action="append", type=Path)
        parser.add_argument("--minimum-security-version")
        parser.add_argument("--dry-run", action="store_true")
        arguments = parser.parse_args(argv)
        CodexAgentInternalReleaseMetadataSynchronizer().synchronize(
            InternalReleaseMetadataSyncCommand(
                manifest=arguments.manifest,
                configs=tuple(arguments.config),
                minimum_security_version=arguments.minimum_security_version,
                dry_run=arguments.dry_run,
            )
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(CodexAgentInternalReleaseMetadataSyncCli().execute())
