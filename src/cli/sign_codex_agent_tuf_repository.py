"""Initialize and sign the offline TUF repository for Windows Agent releases."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final, Literal, TypeVar
from zipfile import ZIP_DEFLATED, ZipFile

from cryptography.hazmat.primitives.serialization import (
    BestAvailableEncryption,
    Encoding,
    PrivateFormat,
    load_pem_private_key,
)
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, model_validator
from securesystemslib.signer import CryptoSigner
from tuf.api.metadata import (
    Metadata,
    MetaFile,
    Root,
    Snapshot,
    TargetFile,
    Targets,
    Timestamp,
)

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

TufRole = Literal["root", "targets", "snapshot", "timestamp"]
TUF_ROLES: Final[tuple[TufRole, ...]] = (
    "root",
    "targets",
    "snapshot",
    "timestamp",
)
RELEASE_SIGNING_ROLES: Final[tuple[TufRole, ...]] = (
    "targets",
    "snapshot",
    "timestamp",
)
MINIMUM_KEY_PASSWORD_LENGTH: Final = 16
DEFAULT_ROOT_KEY_COUNT: Final = 3
DEFAULT_ROOT_THRESHOLD: Final = 2
DEFAULT_TARGETS_KEY_COUNT: Final = 3
DEFAULT_TARGETS_THRESHOLD: Final = 2
MAXIMUM_OFFLINE_ROLE_KEY_COUNT: Final = 5
DEFAULT_ROOT_EXPIRATION_DAYS: Final = 730
DEFAULT_TARGETS_EXPIRATION_DAYS: Final = 90
DEFAULT_SNAPSHOT_EXPIRATION_DAYS: Final = 30
DEFAULT_TIMESTAMP_EXPIRATION_DAYS: Final = 7
AGENT_TARGET_PREFIX: Final = "codex-remote-agent.exe/windows/x86_64/stable"
AGENT_EXECUTABLE_FILE_NAME: Final = "codex-remote-agent.exe"
TUF_METADATA_FILE_NAMES: Final = ("timestamp.json", "snapshot.json", "targets.json")

MetadataPayload = TypeVar("MetadataPayload", Root, Targets, Snapshot, Timestamp)


@dataclass(frozen=True, slots=True)
class TufPrivateKeySlot:
    """Describe one independently encrypted private key file."""

    role: TufRole
    index: int

    @property
    def file_name(self) -> str:
        return f"{self.role}-{self.index}.pem"

    @property
    def password_environment(self) -> str:
        return f"CODEX_TUF_{self.role.upper()}_KEY_{self.index}_PASSWORD"


class CodexAgentTufInitializeCommand(BaseModel):
    """Inputs for creating the first trusted root and encrypted role keys."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    key_directory: Path
    trusted_root: Path
    root_key_count: int = Field(
        default=DEFAULT_ROOT_KEY_COUNT,
        ge=2,
        le=MAXIMUM_OFFLINE_ROLE_KEY_COUNT,
    )
    root_threshold: int = Field(default=DEFAULT_ROOT_THRESHOLD, ge=2)
    targets_key_count: int = Field(
        default=DEFAULT_TARGETS_KEY_COUNT,
        ge=2,
        le=MAXIMUM_OFFLINE_ROLE_KEY_COUNT,
    )
    targets_threshold: int = Field(default=DEFAULT_TARGETS_THRESHOLD, ge=2)
    root_expiration_days: int = Field(default=DEFAULT_ROOT_EXPIRATION_DAYS, ge=30, le=3650)

    @model_validator(mode="after")
    def validate_distinct_outputs(self) -> CodexAgentTufInitializeCommand:
        trusted_root = self.trusted_root.resolve(strict=False)
        key_directory = self.key_directory.resolve(strict=False)
        if trusted_root == key_directory or trusted_root.is_relative_to(key_directory):
            raise ValueError("Trusted root must be stored outside the private key directory.")
        if self.root_threshold > self.root_key_count:
            raise ValueError("Root threshold cannot exceed the root key count.")
        if self.targets_threshold > self.targets_key_count:
            raise ValueError("Targets threshold cannot exceed the targets key count.")
        return self


class CodexAgentTufSignCommand(BaseModel):
    """Inputs for signing exact Agent and manifest targets for one release."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    key_directory: Path
    trusted_root: Path
    signed_build_directory: Path
    output_directory: Path
    version: str = Field(min_length=1, max_length=64)
    previous_metadata_directory: Path | None = None
    targets_expiration_days: int = Field(default=DEFAULT_TARGETS_EXPIRATION_DAYS, ge=7, le=365)
    snapshot_expiration_days: int = Field(default=DEFAULT_SNAPSHOT_EXPIRATION_DAYS, ge=2, le=180)
    timestamp_expiration_days: int = Field(default=DEFAULT_TIMESTAMP_EXPIRATION_DAYS, ge=1, le=30)

    @model_validator(mode="after")
    def validate_release(self) -> CodexAgentTufSignCommand:
        parse_agent_release_version(self.version)
        if self.snapshot_expiration_days > self.targets_expiration_days:
            raise ValueError("Snapshot metadata cannot outlive targets metadata.")
        if self.timestamp_expiration_days > self.snapshot_expiration_days:
            raise ValueError("Timestamp metadata cannot outlive snapshot metadata.")
        return self


class CodexAgentTufOfflineSigner:
    """Own TUF role separation, metadata versioning, and exact-target signing."""

    def initialize(self, command: CodexAgentTufInitializeCommand) -> None:
        """Generate encrypted role keys and a self-signed consistent-snapshot root."""

        if command.key_directory.exists():
            raise FileExistsError("TUF private key directory already exists.")
        if command.trusted_root.exists():
            raise FileExistsError("TUF trusted root already exists.")
        key_slots = self._build_initial_key_slots(command)
        passwords = self._read_key_passwords(key_slots)
        signers = {slot: CryptoSigner.generate_ed25519() for slot in key_slots}
        root = Root(
            version=1,
            expires=datetime.now(UTC) + timedelta(days=command.root_expiration_days),
            consistent_snapshot=True,
        )
        for slot, signer in signers.items():
            root.add_key(signer.public_key, slot.role)
        root.roles["root"].threshold = command.root_threshold
        root.roles["targets"].threshold = command.targets_threshold
        root_metadata = Metadata(root)
        self._sign_metadata(
            root_metadata,
            tuple(signer for slot, signer in signers.items() if slot.role == "root"),
        )
        root.verify_delegate("root", root_metadata.signed_bytes, root_metadata.signatures)

        command.key_directory.parent.mkdir(parents=True, exist_ok=True)
        command.trusted_root.parent.mkdir(parents=True, exist_ok=True)
        temporary_keys = Path(
            tempfile.mkdtemp(prefix="codex-tuf-keys-", dir=command.key_directory.parent)
        )
        root_file_descriptor, temporary_root_name = tempfile.mkstemp(
            prefix=f".{command.trusted_root.name}.",
            suffix=".tmp",
            dir=command.trusted_root.parent,
        )
        os.close(root_file_descriptor)
        temporary_root = Path(temporary_root_name)
        key_directory_committed = False
        trusted_root_committed = False
        try:
            for slot, signer in signers.items():
                private_key = load_pem_private_key(signer.private_bytes, None)
                pem = private_key.private_bytes(
                    Encoding.PEM,
                    PrivateFormat.PKCS8,
                    BestAvailableEncryption(passwords[slot]),
                )
                key_path = temporary_keys / slot.file_name
                key_path.write_bytes(pem)
                key_path.chmod(0o600)
            temporary_root.write_bytes(root_metadata.to_bytes())
            temporary_keys.replace(command.key_directory)
            key_directory_committed = True
            temporary_root.rename(command.trusted_root)
            trusted_root_committed = True
        finally:
            if not trusted_root_committed and key_directory_committed:
                shutil.rmtree(command.key_directory, ignore_errors=True)
            if temporary_keys.exists():
                shutil.rmtree(temporary_keys, ignore_errors=True)
            temporary_root.unlink(missing_ok=True)

    def sign_release(self, command: CodexAgentTufSignCommand) -> None:
        """Create versioned top-level metadata for one exact signed Agent build."""

        if command.output_directory.exists():
            raise FileExistsError("TUF metadata output directory already exists.")
        root_metadata = self._read_root_metadata(command.trusted_root)
        root = root_metadata.signed
        if root.is_expired():
            raise ValueError("TUF trusted root is expired.")
        if not root.consistent_snapshot:
            raise ValueError("TUF trusted root must enable consistent snapshots.")
        root.verify_delegate("root", root_metadata.signed_bytes, root_metadata.signatures)
        signers = self._load_release_signers(command.key_directory, root)
        build_record, manifest, executable = self._read_signed_build(command)
        versions = self._next_metadata_versions(
            command.previous_metadata_directory,
            root,
        )
        now = datetime.now(UTC)
        target_path = f"{AGENT_TARGET_PREFIX}/{command.version}"
        targets_metadata = Metadata(
            Targets(
                version=versions["targets"],
                expires=now + timedelta(days=command.targets_expiration_days),
                targets={
                    target_path: TargetFile.from_data(
                        target_path,
                        executable,
                        ["sha256"],
                    ),
                    AGENT_RELEASE_MANIFEST_TARGET_PATH: TargetFile.from_data(
                        AGENT_RELEASE_MANIFEST_TARGET_PATH,
                        manifest,
                        ["sha256"],
                    ),
                },
            )
        )
        self._sign_metadata(targets_metadata, signers["targets"])
        targets_bytes = targets_metadata.to_bytes()
        snapshot_metadata = Metadata(
            Snapshot(
                version=versions["snapshot"],
                expires=now + timedelta(days=command.snapshot_expiration_days),
                meta={
                    "targets.json": MetaFile.from_data(
                        versions["targets"], targets_bytes, ["sha256"]
                    )
                },
            )
        )
        self._sign_metadata(snapshot_metadata, signers["snapshot"])
        snapshot_bytes = snapshot_metadata.to_bytes()
        timestamp_metadata = Metadata(
            Timestamp(
                version=versions["timestamp"],
                expires=now + timedelta(days=command.timestamp_expiration_days),
                snapshot_meta=MetaFile.from_data(versions["snapshot"], snapshot_bytes, ["sha256"]),
            )
        )
        self._sign_metadata(timestamp_metadata, signers["timestamp"])

        temporary_directory = command.output_directory.with_name(
            f".{command.output_directory.name}.tmp"
        )
        if temporary_directory.exists():
            raise FileExistsError("Temporary TUF metadata directory already exists.")
        command.output_directory.parent.mkdir(parents=True, exist_ok=True)
        temporary_directory.mkdir()
        try:
            (temporary_directory / "targets.json").write_bytes(targets_bytes)
            (temporary_directory / "snapshot.json").write_bytes(snapshot_bytes)
            (temporary_directory / "timestamp.json").write_bytes(timestamp_metadata.to_bytes())
            archive_path = temporary_directory / "tuf-metadata.zip"
            with ZipFile(archive_path, "w", ZIP_DEFLATED) as archive:
                for file_name in TUF_METADATA_FILE_NAMES:
                    archive.write(temporary_directory / file_name, file_name)
            self._verify_release_metadata(
                command=command,
                metadata_directory=temporary_directory,
                build_record=build_record,
            )
            temporary_directory.replace(command.output_directory)
        except BaseException:
            shutil.rmtree(temporary_directory, ignore_errors=True)
            raise

    def _read_signed_build(
        self, command: CodexAgentTufSignCommand
    ) -> tuple[CodexAgentSignedBuildRecord, bytes, bytes]:
        build_record_path = command.signed_build_directory / "release-build.json"
        manifest_path = command.signed_build_directory / AGENT_RELEASE_MANIFEST_TARGET_PATH
        executable_path = command.signed_build_directory / AGENT_EXECUTABLE_FILE_NAME
        for path in (build_record_path, manifest_path, executable_path):
            if not path.is_file():
                raise FileNotFoundError(f"Required signed build file is missing: {path}")
        build_record = CodexAgentSignedBuildRecord.model_validate_json(
            build_record_path.read_bytes()
        )
        manifest_bytes = manifest_path.read_bytes()
        manifest = CodexAgentReleaseManifestEnvelope.model_validate_json(manifest_bytes)
        executable = executable_path.read_bytes()
        expected_target = (
            command.signed_build_directory / "targets" / AGENT_TARGET_PREFIX / command.version
        )
        mismatches = (
            build_record.version != command.version,
            manifest.detail.version != command.version,
            build_record.executable_length != len(executable),
            build_record.executable_sha256 != manifest.detail.digest_sha256,
            build_record.executable_sha256 != hashlib.sha256(executable).hexdigest(),
            not expected_target.is_file(),
            expected_target.is_file() and expected_target.read_bytes() != executable,
        )
        if any(mismatches):
            raise ValueError("Signed build documents do not describe the exact Agent executable.")
        return build_record, manifest_bytes, executable

    def _next_metadata_versions(
        self,
        previous_directory: Path | None,
        root: Root,
    ) -> dict[str, int]:
        if previous_directory is None:
            return {role: 1 for role in ("targets", "snapshot", "timestamp")}
        targets = self._read_targets_metadata(previous_directory / "targets.json")
        snapshot = self._read_snapshot_metadata(previous_directory / "snapshot.json")
        timestamp = self._read_timestamp_metadata(previous_directory / "timestamp.json")
        root.verify_delegate("targets", targets.signed_bytes, targets.signatures)
        root.verify_delegate("snapshot", snapshot.signed_bytes, snapshot.signatures)
        root.verify_delegate("timestamp", timestamp.signed_bytes, timestamp.signatures)
        return {
            "targets": targets.signed.version + 1,
            "snapshot": snapshot.signed.version + 1,
            "timestamp": timestamp.signed.version + 1,
        }

    def _load_release_signers(
        self,
        key_directory: Path,
        root: Root,
    ) -> dict[TufRole, tuple[CryptoSigner, ...]]:
        signers: dict[TufRole, tuple[CryptoSigner, ...]] = {}
        for role in RELEASE_SIGNING_ROLES:
            role_slots = tuple(
                TufPrivateKeySlot(role=role, index=index)
                for index in range(1, len(root.roles[role].keyids) + 1)
                if (key_directory / TufPrivateKeySlot(role=role, index=index).file_name).is_file()
            )
            if len(role_slots) < root.roles[role].threshold:
                raise FileNotFoundError(
                    f"TUF {role} requires {root.roles[role].threshold} authorized private keys; "
                    f"found {len(role_slots)}."
                )
            passwords = self._read_key_passwords(role_slots)
            role_signers: list[CryptoSigner] = []
            for slot in role_slots:
                key_path = key_directory / slot.file_name
                private_key = load_pem_private_key(
                    key_path.read_bytes(),
                    passwords[slot],
                )
                signer = CryptoSigner(private_key)
                if signer.public_key.keyid not in root.roles[role].keyids:
                    raise ValueError(
                        f"TUF {role} private key {slot.file_name} is not authorized "
                        "by the trusted root."
                    )
                role_signers.append(signer)
            signers[role] = tuple(role_signers)
        return signers

    def _verify_release_metadata(
        self,
        *,
        command: CodexAgentTufSignCommand,
        metadata_directory: Path,
        build_record: CodexAgentSignedBuildRecord,
    ) -> None:
        verification_command = CodexAgentTufVerificationCommand.model_validate(
            {
                "trusted_root": command.trusted_root,
                "metadata_directory": metadata_directory,
                "target_file": command.signed_build_directory / AGENT_EXECUTABLE_FILE_NAME,
                "version": command.version,
                "release_manifest": command.signed_build_directory
                / AGENT_RELEASE_MANIFEST_TARGET_PATH,
                "build_record": command.signed_build_directory / "release-build.json",
                "expected_source_repository": build_record.source_repository,
                "expected_source_revision": build_record.source_revision,
                "expected_release_base_url": str(build_record.cdn_base_url),
            }
        )
        CodexAgentTufMetadataVerifier().verify(verification_command)

    @staticmethod
    def _build_initial_key_slots(
        command: CodexAgentTufInitializeCommand,
    ) -> tuple[TufPrivateKeySlot, ...]:
        return (
            *(
                TufPrivateKeySlot(role="root", index=index)
                for index in range(1, command.root_key_count + 1)
            ),
            *(
                TufPrivateKeySlot(role="targets", index=index)
                for index in range(1, command.targets_key_count + 1)
            ),
            TufPrivateKeySlot(role="snapshot", index=1),
            TufPrivateKeySlot(role="timestamp", index=1),
        )

    @staticmethod
    def _read_key_passwords(
        key_slots: tuple[TufPrivateKeySlot, ...],
    ) -> dict[TufPrivateKeySlot, bytes]:
        passwords: dict[TufPrivateKeySlot, bytes] = {}
        for slot in key_slots:
            value = os.environ.get(slot.password_environment, "")
            if len(value) < MINIMUM_KEY_PASSWORD_LENGTH:
                raise ValueError(
                    f"{slot.password_environment} must contain at least "
                    f"{MINIMUM_KEY_PASSWORD_LENGTH} characters."
                )
            passwords[slot] = value.encode("utf-8")
        return passwords

    @staticmethod
    def _sign_metadata(
        metadata: Metadata[MetadataPayload],
        signers: tuple[CryptoSigner, ...],
    ) -> None:
        if not signers:
            raise ValueError("At least one TUF signer is required.")
        for index, signer in enumerate(signers):
            metadata.sign(signer, append=index > 0)

    @staticmethod
    def _read_metadata_bytes(path: Path, role: TufRole) -> bytes:
        if not path.is_file():
            raise FileNotFoundError(f"TUF {role} metadata is missing: {path}")
        return path.read_bytes()

    @classmethod
    def _read_root_metadata(cls, path: Path) -> Metadata[Root]:
        metadata: Metadata[Root] = Metadata.from_bytes(cls._read_metadata_bytes(path, "root"))
        if not isinstance(metadata.signed, Root):
            raise ValueError("TUF root metadata has the wrong signed type.")
        return metadata

    @classmethod
    def _read_targets_metadata(cls, path: Path) -> Metadata[Targets]:
        metadata: Metadata[Targets] = Metadata.from_bytes(cls._read_metadata_bytes(path, "targets"))
        if not isinstance(metadata.signed, Targets):
            raise ValueError("TUF targets metadata has the wrong signed type.")
        return metadata

    @classmethod
    def _read_snapshot_metadata(cls, path: Path) -> Metadata[Snapshot]:
        metadata: Metadata[Snapshot] = Metadata.from_bytes(
            cls._read_metadata_bytes(path, "snapshot")
        )
        if not isinstance(metadata.signed, Snapshot):
            raise ValueError("TUF snapshot metadata has the wrong signed type.")
        return metadata

    @classmethod
    def _read_timestamp_metadata(cls, path: Path) -> Metadata[Timestamp]:
        metadata: Metadata[Timestamp] = Metadata.from_bytes(
            cls._read_metadata_bytes(path, "timestamp")
        )
        if not isinstance(metadata.signed, Timestamp):
            raise ValueError("TUF timestamp metadata has the wrong signed type.")
        return metadata


class CodexAgentTufOfflineSigningCli:
    """Command-line interface for explicit offline TUF operations."""

    def execute(self, argv: Sequence[str] | None = None) -> int:
        parser = argparse.ArgumentParser(description="Manage Codex Agent offline TUF metadata")
        subparsers = parser.add_subparsers(dest="command", required=True)
        initialize = subparsers.add_parser("initialize")
        initialize.add_argument("--key-directory", required=True, type=Path)
        initialize.add_argument("--trusted-root", required=True, type=Path)
        initialize.add_argument("--root-key-count", type=int, default=DEFAULT_ROOT_KEY_COUNT)
        initialize.add_argument("--root-threshold", type=int, default=DEFAULT_ROOT_THRESHOLD)
        initialize.add_argument("--targets-key-count", type=int, default=DEFAULT_TARGETS_KEY_COUNT)
        initialize.add_argument("--targets-threshold", type=int, default=DEFAULT_TARGETS_THRESHOLD)
        initialize.add_argument(
            "--root-expiration-days", type=int, default=DEFAULT_ROOT_EXPIRATION_DAYS
        )
        sign = subparsers.add_parser("sign-release")
        sign.add_argument("--key-directory", required=True, type=Path)
        sign.add_argument("--trusted-root", required=True, type=Path)
        sign.add_argument("--signed-build-directory", required=True, type=Path)
        sign.add_argument("--output-directory", required=True, type=Path)
        sign.add_argument("--version", required=True)
        sign.add_argument("--previous-metadata-directory", type=Path)
        sign.add_argument(
            "--targets-expiration-days", type=int, default=DEFAULT_TARGETS_EXPIRATION_DAYS
        )
        sign.add_argument(
            "--snapshot-expiration-days", type=int, default=DEFAULT_SNAPSHOT_EXPIRATION_DAYS
        )
        sign.add_argument(
            "--timestamp-expiration-days", type=int, default=DEFAULT_TIMESTAMP_EXPIRATION_DAYS
        )
        arguments = parser.parse_args(argv)
        signer = CodexAgentTufOfflineSigner()
        if arguments.command == "initialize":
            signer.initialize(
                CodexAgentTufInitializeCommand(
                    key_directory=arguments.key_directory,
                    trusted_root=arguments.trusted_root,
                    root_key_count=arguments.root_key_count,
                    root_threshold=arguments.root_threshold,
                    targets_key_count=arguments.targets_key_count,
                    targets_threshold=arguments.targets_threshold,
                    root_expiration_days=arguments.root_expiration_days,
                )
            )
            logger.info("TUF role keys and trusted root initialized.")
            return 0
        signer.sign_release(
            CodexAgentTufSignCommand(
                key_directory=arguments.key_directory,
                trusted_root=arguments.trusted_root,
                signed_build_directory=arguments.signed_build_directory,
                output_directory=arguments.output_directory,
                version=arguments.version,
                previous_metadata_directory=arguments.previous_metadata_directory,
                targets_expiration_days=arguments.targets_expiration_days,
                snapshot_expiration_days=arguments.snapshot_expiration_days,
                timestamp_expiration_days=arguments.timestamp_expiration_days,
            )
        )
        logger.info("TUF metadata and CI archive signed and verified.")
        return 0


if __name__ == "__main__":
    raise SystemExit(CodexAgentTufOfflineSigningCli().execute())
