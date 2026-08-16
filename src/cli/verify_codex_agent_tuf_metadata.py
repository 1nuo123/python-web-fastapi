"""Verify offline-signed TUF metadata against an exact Agent build."""

from __future__ import annotations

import argparse
import hashlib
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator
from tuf.api.metadata import Metadata, Root, Snapshot, Targets, Timestamp

from src.core.codex_contract.agent_release_manifest_contract import (
    AGENT_RELEASE_MANIFEST_TARGET_PATH,
    CodexAgentReleaseManifestEnvelope,
)

TARGET_PREFIX: Final = "codex-remote-agent.exe/windows/x86_64/stable"


class CodexAgentSignedBuildRecord(BaseModel):
    """Immutable values recorded immediately after Authenticode signing."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_repository: str = Field(min_length=1, max_length=256)
    source_revision: str = Field(min_length=40, max_length=64)
    version: str = Field(min_length=1, max_length=64)
    minimum_security_version: str = Field(min_length=1, max_length=64)
    rollout_percent: int = Field(ge=0, le=100)
    cdn_base_url: HttpUrl
    executable_length: int = Field(gt=0)
    executable_sha256: str = Field(min_length=64, max_length=64)
    authenticode_signer_sha256: str = Field(min_length=64, max_length=64)

    @field_validator("executable_sha256", "authenticode_signer_sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        """Require a canonical lowercase SHA-256 digest."""

        normalized = value.lower()
        if any(character not in "0123456789abcdef" for character in normalized):
            raise ValueError("SHA-256 value is not hexadecimal.")
        return normalized

    @field_validator("source_revision")
    @classmethod
    def validate_source_revision(cls, value: str) -> str:
        """Require a canonical lowercase Git object identifier."""

        normalized = value.lower()
        if any(character not in "0123456789abcdef" for character in normalized):
            raise ValueError("Source revision is not hexadecimal.")
        return normalized


class CodexAgentTufVerificationCommand(BaseModel):
    """Inputs required to authorize a signed build for publication."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    trusted_root: Path
    metadata_directory: Path
    target_file: Path
    version: str = Field(min_length=1, max_length=64)
    release_manifest: Path
    build_record: Path
    expected_source_repository: str = Field(min_length=1, max_length=256)
    expected_source_revision: str = Field(min_length=40, max_length=64)
    expected_release_base_url: HttpUrl


class CodexAgentTufMetadataVerifier:
    """Verify the top-level TUF chain and exact Agent release bytes."""

    def verify(self, command: CodexAgentTufVerificationCommand) -> None:
        """Reject stale, unsigned, mismatched, or substituted release inputs."""

        root_bytes = self._read_file(command.trusted_root)
        timestamp_bytes = self._read_file(command.metadata_directory / "timestamp.json")
        snapshot_bytes = self._read_file(command.metadata_directory / "snapshot.json")
        targets_bytes = self._read_file(command.metadata_directory / "targets.json")
        target_bytes = self._read_file(command.target_file)
        manifest_bytes = self._read_file(command.release_manifest)

        root_metadata = Metadata.from_bytes(root_bytes)
        if not isinstance(root_metadata.signed, Root):
            raise ValueError("Trusted root file does not contain root metadata.")
        root = root_metadata.signed
        if not root.consistent_snapshot:
            raise ValueError("TUF trusted root must enable consistent snapshots.")
        root.verify_delegate("root", root_metadata.signed_bytes, root_metadata.signatures)
        self._reject_expired(root, "root")

        timestamp_metadata = Metadata.from_bytes(timestamp_bytes)
        if not isinstance(timestamp_metadata.signed, Timestamp):
            raise ValueError("timestamp.json does not contain timestamp metadata.")
        timestamp = timestamp_metadata.signed
        root.verify_delegate(
            "timestamp",
            timestamp_metadata.signed_bytes,
            timestamp_metadata.signatures,
        )
        self._reject_expired(timestamp, "timestamp")
        timestamp.snapshot_meta.verify_length_and_hashes(snapshot_bytes)

        snapshot_metadata = Metadata.from_bytes(snapshot_bytes)
        if not isinstance(snapshot_metadata.signed, Snapshot):
            raise ValueError("snapshot.json does not contain snapshot metadata.")
        snapshot = snapshot_metadata.signed
        if timestamp.snapshot_meta.version != snapshot.version:
            raise ValueError("Snapshot version does not match timestamp metadata.")
        root.verify_delegate(
            "snapshot",
            snapshot_metadata.signed_bytes,
            snapshot_metadata.signatures,
        )
        self._reject_expired(snapshot, "snapshot")

        targets_file = snapshot.meta.get("targets.json")
        if targets_file is None:
            raise ValueError("Snapshot metadata does not describe targets.json.")
        targets_file.verify_length_and_hashes(targets_bytes)
        targets_metadata = Metadata.from_bytes(targets_bytes)
        if not isinstance(targets_metadata.signed, Targets):
            raise ValueError("targets.json does not contain targets metadata.")
        targets = targets_metadata.signed
        if targets_file.version != targets.version:
            raise ValueError("Targets version does not match snapshot metadata.")
        root.verify_delegate(
            "targets",
            targets_metadata.signed_bytes,
            targets_metadata.signatures,
        )
        self._reject_expired(targets, "targets")

        target_path = f"{TARGET_PREFIX}/{command.version}"
        target = targets.targets.get(target_path)
        if target is None:
            raise ValueError(f"TUF metadata does not authorize target {target_path}.")
        target.verify_length_and_hashes(target_bytes)
        manifest_target = targets.targets.get(AGENT_RELEASE_MANIFEST_TARGET_PATH)
        if manifest_target is None:
            raise ValueError(
                f"TUF metadata does not authorize target {AGENT_RELEASE_MANIFEST_TARGET_PATH}."
            )
        target_sha256_values: dict[str, str] = {}
        for target_name, target_info in (
            (target_path, target),
            (AGENT_RELEASE_MANIFEST_TARGET_PATH, manifest_target),
        ):
            if tuple(target_info.hashes) != ("sha256",):
                raise ValueError(f"TUF target {target_name} must use only SHA-256.")
            target_sha256 = target_info.hashes["sha256"]
            target_sha256_values[target_name] = target_sha256
        manifest_target.verify_length_and_hashes(manifest_bytes)
        self._verify_release_documents(
            command=command,
            target_path=target_path,
            target_bytes=target_bytes,
            manifest_bytes=manifest_bytes,
            target_sha256=target_sha256_values[target_path],
        )

    def _verify_release_documents(
        self,
        *,
        command: CodexAgentTufVerificationCommand,
        target_path: str,
        target_bytes: bytes,
        manifest_bytes: bytes,
        target_sha256: str,
    ) -> None:
        digest = hashlib.sha256(target_bytes).hexdigest()
        build_record = CodexAgentSignedBuildRecord.model_validate_json(
            self._read_file(command.build_record)
        )
        manifest = CodexAgentReleaseManifestEnvelope.model_validate_json(manifest_bytes)
        expected_download_url = (
            f"{str(build_record.cdn_base_url).rstrip('/')}/targets/"
            f"{TARGET_PREFIX}/{digest}.{command.version}"
        )
        mismatches = (
            build_record.source_repository != command.expected_source_repository,
            build_record.source_revision != command.expected_source_revision,
            str(build_record.cdn_base_url).rstrip("/")
            != str(command.expected_release_base_url).rstrip("/"),
            build_record.version != command.version,
            build_record.executable_length != len(target_bytes),
            build_record.executable_sha256 != digest,
            target_sha256 != digest,
            manifest.detail.version != command.version,
            manifest.detail.digest_sha256 != digest,
            manifest.detail.download_url != expected_download_url,
            manifest.detail.minimum_security_version != build_record.minimum_security_version,
            manifest.detail.rollout_percent != build_record.rollout_percent,
        )
        if any(mismatches):
            raise ValueError("Release manifest or build record does not match the signed target.")

    @staticmethod
    def _read_file(path: Path) -> bytes:
        if not path.is_file():
            raise FileNotFoundError(f"Required release file is missing: {path}")
        return path.read_bytes()

    @staticmethod
    def _reject_expired(metadata: Root | Timestamp | Snapshot | Targets, role: str) -> None:
        if metadata.is_expired():
            raise ValueError(f"TUF {role} metadata is expired.")


class CodexAgentTufMetadataVerificationCli:
    """CLI entry point for the verified publish gate."""

    def execute(self, argv: Sequence[str] | None = None) -> int:
        parser = argparse.ArgumentParser(
            description="Verify TUF metadata against an exact signed Agent build"
        )
        parser.add_argument("--trusted-root", required=True, type=Path)
        parser.add_argument("--metadata-directory", required=True, type=Path)
        parser.add_argument("--target-file", required=True, type=Path)
        parser.add_argument("--version", required=True)
        parser.add_argument("--release-manifest", required=True, type=Path)
        parser.add_argument("--build-record", required=True, type=Path)
        parser.add_argument("--expected-source-repository", required=True)
        parser.add_argument("--expected-source-revision", required=True)
        parser.add_argument("--expected-release-base-url", required=True)
        arguments = parser.parse_args(argv)
        command = CodexAgentTufVerificationCommand(
            trusted_root=arguments.trusted_root,
            metadata_directory=arguments.metadata_directory,
            target_file=arguments.target_file,
            version=arguments.version,
            release_manifest=arguments.release_manifest,
            build_record=arguments.build_record,
            expected_source_repository=arguments.expected_source_repository,
            expected_source_revision=arguments.expected_source_revision,
            expected_release_base_url=arguments.expected_release_base_url,
        )
        CodexAgentTufMetadataVerifier().verify(command)
        logger.info("TUF metadata matches the exact signed Agent build.")
        return 0


if __name__ == "__main__":
    raise SystemExit(CodexAgentTufMetadataVerificationCli().execute())
