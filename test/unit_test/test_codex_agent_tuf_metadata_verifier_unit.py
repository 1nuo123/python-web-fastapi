"""Verified-publish gate tests for signed Windows Agent releases."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
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

from src.cli.build_codex_agent_release_assets import (
    AgentReleaseAssetsCommand,
    CodexAgentReleaseAssetsBuilder,
)
from src.cli.stage_codex_agent_release_repository import (
    AGENT_EXECUTABLE_FILE_NAME,
    AGENT_INSTALLER_FILE_NAME,
    AGENT_TARGET_PREFIX,
    CodexAgentReleaseRepositoryStageCommand,
    CodexAgentReleaseRepositoryStager,
)
from src.cli.verify_codex_agent_tuf_metadata import (
    CodexAgentTufMetadataVerifier,
    CodexAgentTufVerificationCommand,
)

VERSION = "1.2.3"
MINIMUM_SECURITY_VERSION = "1.1.0"
CDN_BASE_URL = "https://updates.acme.dev"
SOURCE_REPOSITORY = "acme/codex-agent"
SOURCE_REVISION = "a" * 40


def test_verifier_should_accept_exact_signed_metadata_chain(tmp_path: Path) -> None:
    command = _build_release(tmp_path)

    CodexAgentTufMetadataVerifier().verify(command)


def test_verifier_should_reject_tampered_executable(tmp_path: Path) -> None:
    command = _build_release(tmp_path)
    command.target_file.write_bytes(b"tampered")

    with pytest.raises(Exception, match="length|hash|signed target"):
        CodexAgentTufMetadataVerifier().verify(command)


def test_verifier_should_reject_manifest_from_other_build(tmp_path: Path) -> None:
    command = _build_release(tmp_path)
    content = command.release_manifest.read_text("utf-8").replace(
        hashlib.sha256(b"agent-release").hexdigest(),
        "0" * 64,
    )
    command.release_manifest.write_text(content, "utf-8")

    with pytest.raises(Exception, match="length|hash"):
        CodexAgentTufMetadataVerifier().verify(command)


def test_verifier_should_reject_re_signed_manifest_from_other_build(tmp_path: Path) -> None:
    command = _build_release(tmp_path, manifest_digest_override="0" * 64)

    with pytest.raises(ValueError, match="does not match"):
        CodexAgentTufMetadataVerifier().verify(command)


def test_verifier_should_reject_unsigned_manifest_target(tmp_path: Path) -> None:
    command = _build_release(tmp_path, include_manifest_target=False)

    with pytest.raises(ValueError, match="does not authorize target codex-agent-release.json"):
        CodexAgentTufMetadataVerifier().verify(command)


def test_verifier_should_reject_root_without_consistent_snapshot(tmp_path: Path) -> None:
    command = _build_release(tmp_path, consistent_snapshot=False)

    with pytest.raises(ValueError, match="consistent snapshots"):
        CodexAgentTufMetadataVerifier().verify(command)


def test_verifier_should_reject_noncanonical_target_hash_algorithms(tmp_path: Path) -> None:
    command = _build_release(tmp_path, target_hash_algorithms=["sha512", "sha256"])

    with pytest.raises(ValueError, match="must use only SHA-256"):
        CodexAgentTufMetadataVerifier().verify(command)


def test_release_assets_should_use_consistent_snapshot_download_url(tmp_path: Path) -> None:
    command = _build_release(tmp_path)
    manifest = command.release_manifest.read_text("utf-8")
    digest = hashlib.sha256(command.target_file.read_bytes()).hexdigest()

    assert (
        f"{CDN_BASE_URL}/targets/codex-remote-agent.exe/windows/x86_64/stable/{digest}.{VERSION}"
    ) in manifest


def test_verifier_should_reject_different_source_revision(tmp_path: Path) -> None:
    command = _build_release(tmp_path).model_copy(update={"expected_source_revision": "b" * 40})

    with pytest.raises(ValueError, match="does not match"):
        CodexAgentTufMetadataVerifier().verify(command)


def test_verifier_should_reject_different_release_base_url(tmp_path: Path) -> None:
    command = _build_release(tmp_path).model_copy(
        update={"expected_release_base_url": "https://other.acme.dev"}
    )

    with pytest.raises(ValueError, match="does not match"):
        CodexAgentTufMetadataVerifier().verify(command)


def test_repository_stager_should_create_complete_atomic_release_tree(tmp_path: Path) -> None:
    command = _build_release(tmp_path)
    repository_root, stage_command = _prepare_repository_stage(tmp_path, command)

    CodexAgentReleaseRepositoryStager().stage(stage_command)

    digest = hashlib.sha256(command.target_file.read_bytes()).hexdigest()
    manifest_bytes = command.release_manifest.read_bytes()
    manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()
    release_root = repository_root / "releases" / VERSION
    assert (repository_root / AGENT_INSTALLER_FILE_NAME).read_bytes() == b"signed-msi"
    assert (repository_root / "codex-agent-release.json").read_bytes() == manifest_bytes
    assert (repository_root / "metadata" / "timestamp.json").is_file()
    assert (repository_root / "metadata" / "1.snapshot.json").is_file()
    assert (repository_root / "metadata" / "1.targets.json").is_file()
    assert (
        repository_root / "targets" / AGENT_TARGET_PREFIX / f"{digest}.{VERSION}"
    ).read_bytes() == command.target_file.read_bytes()
    assert (
        repository_root / "targets" / f"{manifest_digest}.codex-agent-release.json"
    ).read_bytes() == manifest_bytes
    assert not (repository_root / "targets" / AGENT_TARGET_PREFIX / VERSION).exists()
    assert (release_root / AGENT_EXECUTABLE_FILE_NAME).is_file()
    assert (release_root / AGENT_INSTALLER_FILE_NAME).is_file()
    checksums = json.loads((release_root / "SHA256SUMS.json").read_text("utf-8"))
    assert checksums[AGENT_INSTALLER_FILE_NAME] == hashlib.sha256(b"signed-msi").hexdigest()


def test_repository_stager_when_repeated_with_same_bytes_should_be_idempotent(
    tmp_path: Path,
) -> None:
    command = _build_release(tmp_path)
    repository_root, stage_command = _prepare_repository_stage(tmp_path, command)
    stager = CodexAgentReleaseRepositoryStager()

    stager.stage(stage_command)
    first_files = {
        path.relative_to(repository_root).as_posix(): path.read_bytes()
        for path in repository_root.rglob("*")
        if path.is_file()
    }
    stager.stage(stage_command)
    second_files = {
        path.relative_to(repository_root).as_posix(): path.read_bytes()
        for path in repository_root.rglob("*")
        if path.is_file()
    }

    assert second_files == first_files


def test_repository_stager_when_same_version_has_other_bytes_should_reject(
    tmp_path: Path,
) -> None:
    command = _build_release(tmp_path)
    _, stage_command = _prepare_repository_stage(tmp_path, command)
    stager = CodexAgentReleaseRepositoryStager()
    stager.stage(stage_command)
    stage_command.installer.write_bytes(b"other-signed-msi")

    with pytest.raises(FileExistsError, match="Immutable release path"):
        stager.stage(stage_command)


def _build_release(
    tmp_path: Path,
    *,
    include_manifest_target: bool = True,
    consistent_snapshot: bool = True,
    manifest_digest_override: str | None = None,
    target_hash_algorithms: list[str] | None = None,
) -> CodexAgentTufVerificationCommand:
    target_file = tmp_path / "codex-remote-agent.exe"
    target_file.write_bytes(b"agent-release")
    release_root = tmp_path / "release"
    CodexAgentReleaseAssetsBuilder().build(
        AgentReleaseAssetsCommand(
            executable=target_file,
            output_directory=release_root,
            version=VERSION,
            minimum_security_version=MINIMUM_SECURITY_VERSION,
            cdn_base_url=CDN_BASE_URL,
            rollout_percent=100,
        )
    )
    if manifest_digest_override is not None:
        manifest_path = release_root / "codex-agent-release.json"
        manifest_payload = json.loads(manifest_path.read_text("utf-8"))
        manifest_payload["detail"]["digest_sha256"] = manifest_digest_override
        manifest_path.write_text(
            f"{json.dumps(manifest_payload, ensure_ascii=False, indent=2)}\n",
            "utf-8",
        )
    digest = hashlib.sha256(target_file.read_bytes()).hexdigest()
    build_record = release_root / "release-build.json"
    build_record.write_text(
        (
            "{\n"
            f'  "source_repository": "{SOURCE_REPOSITORY}",\n'
            f'  "source_revision": "{SOURCE_REVISION}",\n'
            f'  "version": "{VERSION}",\n'
            f'  "minimum_security_version": "{MINIMUM_SECURITY_VERSION}",\n'
            '  "rollout_percent": 100,\n'
            f'  "cdn_base_url": "{CDN_BASE_URL}",\n'
            f'  "executable_length": {target_file.stat().st_size},\n'
            f'  "executable_sha256": "{digest}",\n'
            f'  "authenticode_signer_sha256": "{"c" * 64}"\n'
            "}\n"
        ),
        "utf-8",
    )
    metadata_directory = tmp_path / "metadata"
    metadata_directory.mkdir()
    trusted_root = tmp_path / "root.json"
    _write_signed_tuf_repository(
        trusted_root=trusted_root,
        metadata_directory=metadata_directory,
        target_file=target_file,
        manifest_file=release_root / "codex-agent-release.json",
        include_manifest_target=include_manifest_target,
        consistent_snapshot=consistent_snapshot,
        target_hash_algorithms=target_hash_algorithms,
    )
    return CodexAgentTufVerificationCommand(
        trusted_root=trusted_root,
        metadata_directory=metadata_directory,
        target_file=target_file,
        version=VERSION,
        release_manifest=release_root / "codex-agent-release.json",
        build_record=build_record,
        expected_source_repository=SOURCE_REPOSITORY,
        expected_source_revision=SOURCE_REVISION,
        expected_release_base_url=CDN_BASE_URL,
    )


def _prepare_repository_stage(
    tmp_path: Path,
    command: CodexAgentTufVerificationCommand,
) -> tuple[Path, CodexAgentReleaseRepositoryStageCommand]:
    signed_build_directory = command.release_manifest.parent
    executable = signed_build_directory / AGENT_EXECUTABLE_FILE_NAME
    executable.write_bytes(command.target_file.read_bytes())
    repository_root = tmp_path / "public-repository"
    repository_root.mkdir()
    installer = tmp_path / AGENT_INSTALLER_FILE_NAME
    installer.write_bytes(b"signed-msi")
    stage_command = CodexAgentReleaseRepositoryStageCommand(
        repository_root=repository_root,
        trusted_root=command.trusted_root,
        metadata_directory=command.metadata_directory,
        signed_build_directory=signed_build_directory,
        installer=installer,
        version=VERSION,
        expected_source_repository=SOURCE_REPOSITORY,
        expected_source_revision=SOURCE_REVISION,
        expected_release_base_url=CDN_BASE_URL,
    )
    return repository_root, stage_command


def _write_signed_tuf_repository(
    *,
    trusted_root: Path,
    metadata_directory: Path,
    target_file: Path,
    manifest_file: Path,
    include_manifest_target: bool,
    consistent_snapshot: bool,
    target_hash_algorithms: list[str] | None,
) -> None:
    signers = {
        role: CryptoSigner.generate_ed25519()
        for role in ("root", "timestamp", "snapshot", "targets")
    }
    expires = datetime.now(UTC) + timedelta(days=7)
    root = Root(version=1, expires=expires, consistent_snapshot=consistent_snapshot)
    for role, signer in signers.items():
        root.add_key(signer.public_key, role)
    root_metadata = Metadata(root)
    root_metadata.sign(signers["root"])
    trusted_root.write_bytes(root_metadata.to_bytes())

    target_path = f"codex-remote-agent.exe/windows/x86_64/stable/{VERSION}"
    signed_targets = {
        target_path: TargetFile.from_data(
            target_path,
            target_file.read_bytes(),
            target_hash_algorithms,
        )
    }
    if include_manifest_target:
        signed_targets["codex-agent-release.json"] = TargetFile.from_data(
            "codex-agent-release.json",
            manifest_file.read_bytes(),
        )
    targets = Metadata(
        Targets(
            version=1,
            expires=expires,
            targets=signed_targets,
        )
    )
    targets.sign(signers["targets"])
    targets_bytes = targets.to_bytes()
    (metadata_directory / "targets.json").write_bytes(targets_bytes)

    snapshot = Metadata(
        Snapshot(
            version=1,
            expires=expires,
            meta={"targets.json": MetaFile.from_data(1, targets_bytes, ["sha256"])},
        )
    )
    snapshot.sign(signers["snapshot"])
    snapshot_bytes = snapshot.to_bytes()
    (metadata_directory / "snapshot.json").write_bytes(snapshot_bytes)

    timestamp = Metadata(
        Timestamp(
            version=1,
            expires=expires,
            snapshot_meta=MetaFile.from_data(1, snapshot_bytes, ["sha256"]),
        )
    )
    timestamp.sign(signers["timestamp"])
    (metadata_directory / "timestamp.json").write_bytes(timestamp.to_bytes())
