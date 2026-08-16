"""Stage and verify the public Codex Remote Agent release repository."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Final, cast

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, field_validator
from tuf.api.metadata import Metadata, Root, Snapshot, Targets

from src.cli.verify_codex_agent_tuf_metadata import (
    CodexAgentSignedBuildRecord,
    CodexAgentTufMetadataVerifier,
    CodexAgentTufVerificationCommand,
)
from src.core.codex_contract.agent_release_manifest_contract import (
    AGENT_RELEASE_MANIFEST_TARGET_PATH,
    CodexAgentReleaseManifestEnvelope,
    parse_agent_release_version,
)

AGENT_EXECUTABLE_FILE_NAME: Final = "codex-remote-agent.exe"
AGENT_INSTALLER_FILE_NAME: Final = "CodexRemoteAgent.msi"
AGENT_TARGET_PREFIX: Final = "codex-remote-agent.exe/windows/x86_64/stable"
RELEASE_DOCUMENT_FILE_NAMES: Final = (
    "codex-agent-release.json",
    "codex-agent.cdx.json",
    "codex-agent.spdx.json",
    "release-build.json",
)


class CodexAgentReleaseRepositoryStageCommand(BaseModel):
    """Inputs used to create one atomic public release repository commit."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    repository_root: Path
    trusted_root: Path
    metadata_directory: Path
    signed_build_directory: Path
    installer: Path
    version: str = Field(min_length=1, max_length=64)
    expected_source_repository: str = Field(min_length=1, max_length=256)
    expected_source_revision: str = Field(min_length=40, max_length=64)
    expected_release_base_url: str = Field(min_length=1, max_length=2_048)

    @field_validator("version")
    @classmethod
    def validate_version(cls, value: str) -> str:
        parse_agent_release_version(value)
        return value


class CodexAgentReleaseRepositoryStager:
    """Build a verified release tree before Git advances the public branch."""

    def stage(self, command: CodexAgentReleaseRepositoryStageCommand) -> None:
        """Write immutable release files first and stable pointers last."""

        sources = self._read_sources(command)
        self._verify_signed_release(command, sources)
        repository_root = command.repository_root.resolve()
        if not repository_root.is_dir():
            raise FileNotFoundError("Public release repository checkout is missing.")

        root = cast(Metadata[Root], self._read_metadata(sources["trusted_root"], Root, "root"))
        if not root.signed.consistent_snapshot:
            raise ValueError("TUF root must require consistent snapshots.")
        snapshot = cast(
            Metadata[Snapshot], self._read_metadata(sources["snapshot"], Snapshot, "snapshot")
        )
        targets = cast(
            Metadata[Targets], self._read_metadata(sources["targets"], Targets, "targets")
        )
        build_record = CodexAgentSignedBuildRecord.model_validate_json(sources["build_record"])
        manifest = CodexAgentReleaseManifestEnvelope.model_validate_json(sources["manifest"])

        digest = build_record.executable_sha256
        manifest_digest = hashlib.sha256(sources["manifest"]).hexdigest()
        release_root = repository_root / "releases" / command.version

        immutable_files = {
            repository_root / "metadata" / f"{root.signed.version}.root.json": sources[
                "trusted_root"
            ],
            repository_root / "metadata" / f"{snapshot.signed.version}.snapshot.json": sources[
                "snapshot"
            ],
            repository_root / "metadata" / f"{targets.signed.version}.targets.json": sources[
                "targets"
            ],
            repository_root
            / "targets"
            / AGENT_TARGET_PREFIX
            / f"{digest}.{command.version}": sources["executable"],
            repository_root
            / "targets"
            / f"{manifest_digest}.{AGENT_RELEASE_MANIFEST_TARGET_PATH}": sources["manifest"],
            release_root / AGENT_EXECUTABLE_FILE_NAME: sources["executable"],
            release_root / AGENT_INSTALLER_FILE_NAME: sources["installer"],
        }
        for file_name in RELEASE_DOCUMENT_FILE_NAMES:
            immutable_files[release_root / file_name] = sources[file_name]

        checksums = {
            path.name: hashlib.sha256(content).hexdigest()
            for path, content in immutable_files.items()
            if path.parent == release_root
        }
        immutable_files[release_root / "SHA256SUMS.json"] = (
            json.dumps(checksums, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")

        for path, content in immutable_files.items():
            self._write_immutable(path, content)

        mutable_files = {
            repository_root / "metadata" / "timestamp.json": sources["timestamp"],
            repository_root / "metadata" / "snapshot.json": sources["snapshot"],
            repository_root / "metadata" / "targets.json": sources["targets"],
            repository_root / AGENT_INSTALLER_FILE_NAME: sources["installer"],
            repository_root / AGENT_RELEASE_MANIFEST_TARGET_PATH: sources["manifest"],
        }
        for path, content in mutable_files.items():
            self._write_mutable(path, content)

        self._verify_repository_tree(
            command=command,
            sources=sources,
            immutable_files=immutable_files,
            mutable_files=mutable_files,
            manifest=manifest,
        )

    def _read_sources(self, command: CodexAgentReleaseRepositoryStageCommand) -> dict[str, bytes]:
        signed_build = command.signed_build_directory
        paths = {
            "trusted_root": command.trusted_root,
            "timestamp": command.metadata_directory / "timestamp.json",
            "snapshot": command.metadata_directory / "snapshot.json",
            "targets": command.metadata_directory / "targets.json",
            "executable": signed_build / AGENT_EXECUTABLE_FILE_NAME,
            "installer": command.installer,
            "manifest": signed_build / "codex-agent-release.json",
            "build_record": signed_build / "release-build.json",
            "codex-agent-release.json": signed_build / "codex-agent-release.json",
            "codex-agent.cdx.json": signed_build / "codex-agent.cdx.json",
            "codex-agent.spdx.json": signed_build / "codex-agent.spdx.json",
            "release-build.json": signed_build / "release-build.json",
        }
        result: dict[str, bytes] = {}
        for name, path in paths.items():
            if not path.is_file():
                raise FileNotFoundError(f"Required release file is missing: {path}")
            result[name] = path.read_bytes()
        return result

    def _verify_signed_release(
        self,
        command: CodexAgentReleaseRepositoryStageCommand,
        sources: dict[str, bytes],
    ) -> None:
        build_record = CodexAgentSignedBuildRecord.model_validate_json(sources["build_record"])
        expected_target = (
            command.signed_build_directory / "targets" / AGENT_TARGET_PREFIX / command.version
        )
        if not expected_target.is_file() or expected_target.read_bytes() != sources["executable"]:
            raise ValueError("Signed build target does not match the Agent executable.")
        if build_record.version != command.version:
            raise ValueError("Signed build version does not match the staged release version.")
        verification_command = CodexAgentTufVerificationCommand.model_validate(
            {
                "trusted_root": command.trusted_root,
                "metadata_directory": command.metadata_directory,
                "target_file": command.signed_build_directory / AGENT_EXECUTABLE_FILE_NAME,
                "version": command.version,
                "release_manifest": command.signed_build_directory
                / AGENT_RELEASE_MANIFEST_TARGET_PATH,
                "build_record": command.signed_build_directory / "release-build.json",
                "expected_source_repository": command.expected_source_repository,
                "expected_source_revision": command.expected_source_revision,
                "expected_release_base_url": command.expected_release_base_url,
            }
        )
        CodexAgentTufMetadataVerifier().verify(verification_command)

    def _verify_repository_tree(
        self,
        *,
        command: CodexAgentReleaseRepositoryStageCommand,
        sources: dict[str, bytes],
        immutable_files: dict[Path, bytes],
        mutable_files: dict[Path, bytes],
        manifest: CodexAgentReleaseManifestEnvelope,
    ) -> None:
        for path, expected in (*immutable_files.items(), *mutable_files.items()):
            if not path.is_file() or path.read_bytes() != expected:
                raise ValueError(f"Staged release repository file mismatch: {path}")
        plain_target = command.repository_root / "targets" / AGENT_TARGET_PREFIX / command.version
        if plain_target.exists():
            raise ValueError("Consistent-snapshot repository must not publish a plain target.")
        expected_prefix = f"{command.expected_release_base_url.rstrip('/')}/targets/"
        if not manifest.detail.download_url.startswith(expected_prefix):
            raise ValueError("Release manifest points outside the public release repository.")

    @staticmethod
    def _read_metadata(
        content: bytes,
        expected_type: type[Root] | type[Snapshot] | type[Targets],
        role: str,
    ) -> Metadata[Root] | Metadata[Snapshot] | Metadata[Targets]:
        metadata = Metadata.from_bytes(content)
        if not isinstance(metadata.signed, expected_type):
            raise ValueError(f"TUF {role} metadata has the wrong signed type.")
        return metadata

    def _write_immutable(self, path: Path, content: bytes) -> None:
        if path.exists():
            if not path.is_file() or path.read_bytes() != content:
                raise FileExistsError(
                    f"Immutable release path already contains other bytes: {path}"
                )
            return
        self._atomic_write(path, content)

    def _write_mutable(self, path: Path, content: bytes) -> None:
        self._atomic_write(path, content)

    @staticmethod
    def _atomic_write(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_name(f".{path.name}.tmp")
        temporary_path.write_bytes(content)
        temporary_path.replace(path)


class CodexAgentReleaseRepositoryStageCli:
    """Command-line entry point for verified public repository staging."""

    def execute(self, argv: Sequence[str] | None = None) -> int:
        parser = argparse.ArgumentParser(
            description="Stage a verified Codex Remote Agent public release repository"
        )
        parser.add_argument("--repository-root", required=True, type=Path)
        parser.add_argument("--trusted-root", required=True, type=Path)
        parser.add_argument("--metadata-directory", required=True, type=Path)
        parser.add_argument("--signed-build-directory", required=True, type=Path)
        parser.add_argument("--installer", required=True, type=Path)
        parser.add_argument("--version", required=True)
        parser.add_argument("--expected-source-repository", required=True)
        parser.add_argument("--expected-source-revision", required=True)
        parser.add_argument("--expected-release-base-url", required=True)
        arguments = parser.parse_args(argv)
        command = CodexAgentReleaseRepositoryStageCommand(
            repository_root=arguments.repository_root,
            trusted_root=arguments.trusted_root,
            metadata_directory=arguments.metadata_directory,
            signed_build_directory=arguments.signed_build_directory,
            installer=arguments.installer,
            version=arguments.version,
            expected_source_repository=arguments.expected_source_repository,
            expected_source_revision=arguments.expected_source_revision,
            expected_release_base_url=arguments.expected_release_base_url,
        )
        CodexAgentReleaseRepositoryStager().stage(command)
        logger.info(
            "Public Agent release repository staged and verified: {}", command.repository_root
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(CodexAgentReleaseRepositoryStageCli().execute())
