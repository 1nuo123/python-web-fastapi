"""Windows Agent 离线 TUF 仓库管理器单元测试。"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from zipfile import ZipFile

import pytest
from cryptography.hazmat.primitives.serialization import (
    BestAvailableEncryption,
    Encoding,
    PrivateFormat,
    load_pem_private_key,
)
from pydantic import ValidationError
from securesystemslib.signer import CryptoSigner
from tuf.api.metadata import Metadata, Root, Snapshot, Targets, Timestamp

from src.cli.sign_codex_agent_tuf_repository import (
    AGENT_EXECUTABLE_FILE_NAME,
    AGENT_TARGET_PREFIX,
    TUF_METADATA_FILE_NAMES,
    CodexAgentTufInitializeCommand,
    CodexAgentTufOfflineSigner,
    CodexAgentTufSignCommand,
    TufPrivateKeySlot,
)
from src.cli.verify_codex_agent_tuf_metadata import CodexAgentSignedBuildRecord
from src.core.codex_contract.agent_release_manifest_contract import (
    AGENT_RELEASE_MANIFEST_TARGET_PATH,
    CodexAgentReleaseManifestDetail,
    CodexAgentReleaseManifestEnvelope,
    CodexAgentReleaseManifestHeader,
)

VERSION = "1.2.3"
NEXT_VERSION = "1.2.4"
MINIMUM_SECURITY_VERSION = "1.1.0"
RELEASE_BASE_URL = "https://updates.acme.dev"
SOURCE_REPOSITORY = "acme/codex-agent"
SOURCE_REVISION = "a" * 40
SIGNER_SHA256 = "c" * 64


def test_initialize_when_password_is_missing_should_reject_without_output(
    tmp_path: Path,
) -> None:
    command = _initialize_command(tmp_path)

    with pytest.raises(ValueError, match="CODEX_TUF_ROOT_KEY_1_PASSWORD"):
        CodexAgentTufOfflineSigner().initialize(command)

    assert not command.key_directory.exists()
    assert not command.trusted_root.exists()


def test_initialize_when_password_is_too_short_should_reject(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command = _initialize_command(tmp_path)
    passwords = _set_tuf_passwords(monkeypatch, command)
    monkeypatch.setenv(TufPrivateKeySlot(role="targets", index=2).password_environment, "short")

    with pytest.raises(ValueError, match="CODEX_TUF_TARGETS_KEY_2_PASSWORD"):
        CodexAgentTufOfflineSigner().initialize(command)

    assert passwords
    assert not command.key_directory.exists()
    assert not command.trusted_root.exists()


@pytest.mark.parametrize(
    "field_name,field_value,error_message",
    [
        ("root_threshold", 4, "Root threshold cannot exceed"),
        ("targets_threshold", 4, "Targets threshold cannot exceed"),
    ],
)
def test_initialize_command_when_threshold_exceeds_key_count_should_reject(
    tmp_path: Path,
    field_name: str,
    field_value: int,
    error_message: str,
) -> None:
    values = {
        "key_directory": tmp_path / "private-keys",
        "trusted_root": tmp_path / "trust" / "root.json",
        field_name: field_value,
    }

    with pytest.raises(ValidationError, match=error_message):
        CodexAgentTufInitializeCommand.model_validate(values)


def test_initialize_should_create_encrypted_threshold_keys_and_trusted_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command = _initialize_command(tmp_path)
    passwords = _set_tuf_passwords(monkeypatch, command)

    CodexAgentTufOfflineSigner().initialize(command)

    expected_slots = _key_slots(command)
    assert {path.name for path in command.key_directory.iterdir()} == {
        slot.file_name for slot in expected_slots
    }
    for slot in expected_slots:
        key_bytes = (command.key_directory / slot.file_name).read_bytes()
        with pytest.raises(TypeError, match="Password was not given"):
            load_pem_private_key(key_bytes, None)
        load_pem_private_key(key_bytes, passwords[slot])

    root_metadata: Metadata[Root] = Metadata.from_bytes(command.trusted_root.read_bytes())
    assert isinstance(root_metadata.signed, Root)
    root = root_metadata.signed
    assert root.consistent_snapshot is True
    assert root.roles["root"].threshold == 2
    assert root.roles["targets"].threshold == 2
    assert len(root.roles["root"].keyids) == 3
    assert len(root.roles["targets"].keyids) == 3
    assert len(root_metadata.signatures) == 3
    root.verify_delegate("root", root_metadata.signed_bytes, root_metadata.signatures)


def test_initialize_when_output_exists_should_refuse_overwrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command = _initialize_command(tmp_path)
    _set_tuf_passwords(monkeypatch, command)
    command.key_directory.mkdir(parents=True)
    sentinel = command.key_directory / "sentinel.txt"
    sentinel.write_text("preserve", encoding="utf-8")

    with pytest.raises(FileExistsError, match="private key directory"):
        CodexAgentTufOfflineSigner().initialize(command)

    assert sentinel.read_text("utf-8") == "preserve"
    assert not command.trusted_root.exists()


def test_initialize_when_final_root_commit_fails_should_remove_partial_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command = _initialize_command(tmp_path)
    _set_tuf_passwords(monkeypatch, command)
    original_rename = Path.rename

    def fail_trusted_root_commit(source: Path, target: Path) -> Path:
        if Path(target) == command.trusted_root:
            raise OSError("simulated root commit failure")
        return original_rename(source, target)

    monkeypatch.setattr(Path, "rename", fail_trusted_root_commit)

    with pytest.raises(OSError, match="simulated root commit failure"):
        CodexAgentTufOfflineSigner().initialize(command)

    assert not command.key_directory.exists()
    assert not command.trusted_root.exists()
    assert not tuple(command.trusted_root.parent.glob(f".{command.trusted_root.name}.*.tmp"))


def test_sign_release_should_create_verified_threshold_metadata_without_root_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    initialize = _initialize_command(tmp_path)
    _set_tuf_passwords(monkeypatch, initialize)
    signer = CodexAgentTufOfflineSigner()
    signer.initialize(initialize)
    (initialize.key_directory / "root-1.pem").unlink()
    for index in range(1, initialize.root_key_count + 1):
        monkeypatch.delenv(
            TufPrivateKeySlot(role="root", index=index).password_environment,
            raising=False,
        )
    signed_build = _write_signed_build(tmp_path / "signed-build", VERSION)
    output = tmp_path / "metadata-v1"

    signer.sign_release(
        _sign_command(
            initialize=initialize,
            signed_build=signed_build,
            output=output,
            version=VERSION,
        )
    )

    targets: Metadata[Targets] = Metadata.from_bytes((output / "targets.json").read_bytes())
    snapshot: Metadata[Snapshot] = Metadata.from_bytes((output / "snapshot.json").read_bytes())
    timestamp: Metadata[Timestamp] = Metadata.from_bytes((output / "timestamp.json").read_bytes())
    assert isinstance(targets.signed, Targets)
    assert isinstance(snapshot.signed, Snapshot)
    assert isinstance(timestamp.signed, Timestamp)
    assert len(targets.signatures) == 3
    assert len(snapshot.signatures) == 1
    assert len(timestamp.signatures) == 1
    with ZipFile(output / "tuf-metadata.zip") as archive:
        assert tuple(archive.namelist()) == TUF_METADATA_FILE_NAMES


def test_sign_release_with_previous_metadata_should_increment_all_versions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    initialize = _initialize_command(tmp_path)
    _set_tuf_passwords(monkeypatch, initialize)
    signer = CodexAgentTufOfflineSigner()
    signer.initialize(initialize)
    first_build = _write_signed_build(tmp_path / "signed-build-v1", VERSION)
    first_output = tmp_path / "metadata-v1"
    signer.sign_release(
        _sign_command(
            initialize=initialize,
            signed_build=first_build,
            output=first_output,
            version=VERSION,
        )
    )
    second_build = _write_signed_build(tmp_path / "signed-build-v2", NEXT_VERSION)
    second_output = tmp_path / "metadata-v2"

    signer.sign_release(
        _sign_command(
            initialize=initialize,
            signed_build=second_build,
            output=second_output,
            version=NEXT_VERSION,
            previous_metadata=first_output,
        )
    )

    assert _metadata_version(second_output / "targets.json", Targets) == 2
    assert _metadata_version(second_output / "snapshot.json", Snapshot) == 2
    assert _metadata_version(second_output / "timestamp.json", Timestamp) == 2


def test_sign_release_when_role_key_is_unauthorized_should_reject(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    initialize = _initialize_command(tmp_path)
    passwords = _set_tuf_passwords(monkeypatch, initialize)
    signer = CodexAgentTufOfflineSigner()
    signer.initialize(initialize)
    slot = TufPrivateKeySlot(role="snapshot", index=1)
    replacement = CryptoSigner.generate_ed25519()
    replacement_key = load_pem_private_key(replacement.private_bytes, None)
    (initialize.key_directory / slot.file_name).write_bytes(
        replacement_key.private_bytes(
            Encoding.PEM,
            PrivateFormat.PKCS8,
            BestAvailableEncryption(passwords[slot]),
        )
    )
    signed_build = _write_signed_build(tmp_path / "signed-build", VERSION)
    output = tmp_path / "metadata"

    with pytest.raises(ValueError, match="not authorized"):
        signer.sign_release(
            _sign_command(
                initialize=initialize,
                signed_build=signed_build,
                output=output,
                version=VERSION,
            )
        )

    assert not output.exists()


@pytest.mark.parametrize(
    "tampered_file", [AGENT_EXECUTABLE_FILE_NAME, AGENT_RELEASE_MANIFEST_TARGET_PATH]
)
def test_sign_release_when_build_is_tampered_should_reject_without_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tampered_file: str,
) -> None:
    initialize = _initialize_command(tmp_path)
    _set_tuf_passwords(monkeypatch, initialize)
    signer = CodexAgentTufOfflineSigner()
    signer.initialize(initialize)
    signed_build = _write_signed_build(tmp_path / "signed-build", VERSION)
    (signed_build / tampered_file).write_bytes(b"tampered")
    output = tmp_path / "metadata"

    with pytest.raises((ValueError, ValidationError), match="exact Agent|validation error"):
        signer.sign_release(
            _sign_command(
                initialize=initialize,
                signed_build=signed_build,
                output=output,
                version=VERSION,
            )
        )

    assert not output.exists()


def test_sign_release_when_final_verification_fails_should_remove_temporary_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    initialize = _initialize_command(tmp_path)
    _set_tuf_passwords(monkeypatch, initialize)
    signer = CodexAgentTufOfflineSigner()
    signer.initialize(initialize)
    signed_build = _write_signed_build(tmp_path / "signed-build", VERSION)
    output = tmp_path / "metadata"

    def reject_metadata(**_arguments: object) -> None:
        raise ValueError("simulated final verification failure")

    monkeypatch.setattr(signer, "_verify_release_metadata", reject_metadata)

    with pytest.raises(ValueError, match="simulated final verification failure"):
        signer.sign_release(
            _sign_command(
                initialize=initialize,
                signed_build=signed_build,
                output=output,
                version=VERSION,
            )
        )

    assert not output.exists()
    assert not output.with_name(f".{output.name}.tmp").exists()


def _initialize_command(tmp_path: Path) -> CodexAgentTufInitializeCommand:
    return CodexAgentTufInitializeCommand(
        key_directory=tmp_path / "private-keys",
        trusted_root=tmp_path / "trust" / "root.json",
    )


def _key_slots(command: CodexAgentTufInitializeCommand) -> tuple[TufPrivateKeySlot, ...]:
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


def _set_tuf_passwords(
    monkeypatch: pytest.MonkeyPatch,
    command: CodexAgentTufInitializeCommand,
) -> dict[TufPrivateKeySlot, bytes]:
    passwords: dict[TufPrivateKeySlot, bytes] = {}
    for slot in _key_slots(command):
        password = f"test-only-{slot.role}-{slot.index}-password".encode()
        passwords[slot] = password
        monkeypatch.setenv(slot.password_environment, password.decode())
    return passwords


def _write_signed_build(directory: Path, version: str) -> Path:
    directory.mkdir(parents=True)
    executable = f"signed-agent-{version}".encode()
    digest = hashlib.sha256(executable).hexdigest()
    executable_path = directory / AGENT_EXECUTABLE_FILE_NAME
    executable_path.write_bytes(executable)
    target_path = directory / "targets" / AGENT_TARGET_PREFIX / version
    target_path.parent.mkdir(parents=True)
    target_path.write_bytes(executable)
    manifest = CodexAgentReleaseManifestEnvelope(
        header=CodexAgentReleaseManifestHeader(),
        detail=CodexAgentReleaseManifestDetail(
            version=version,
            digest_sha256=digest,
            download_url=(f"{RELEASE_BASE_URL}/targets/{AGENT_TARGET_PREFIX}/{digest}.{version}"),
            rollout_percent=100,
            minimum_security_version=MINIMUM_SECURITY_VERSION,
            published_at=datetime.now(UTC),
        ),
    )
    (directory / AGENT_RELEASE_MANIFEST_TARGET_PATH).write_text(
        f"{manifest.model_dump_json(indent=2)}\n",
        encoding="utf-8",
    )
    build_record = CodexAgentSignedBuildRecord.model_validate(
        {
            "source_repository": SOURCE_REPOSITORY,
            "source_revision": SOURCE_REVISION,
            "version": version,
            "minimum_security_version": MINIMUM_SECURITY_VERSION,
            "rollout_percent": 100,
            "cdn_base_url": RELEASE_BASE_URL,
            "executable_length": len(executable),
            "executable_sha256": digest,
            "authenticode_signer_sha256": SIGNER_SHA256,
        }
    )
    (directory / "release-build.json").write_text(
        f"{build_record.model_dump_json(indent=2)}\n",
        encoding="utf-8",
    )
    return directory


def _sign_command(
    *,
    initialize: CodexAgentTufInitializeCommand,
    signed_build: Path,
    output: Path,
    version: str,
    previous_metadata: Path | None = None,
) -> CodexAgentTufSignCommand:
    return CodexAgentTufSignCommand(
        key_directory=initialize.key_directory,
        trusted_root=initialize.trusted_root,
        signed_build_directory=signed_build,
        output_directory=output,
        version=version,
        previous_metadata_directory=previous_metadata,
    )


def _metadata_version(
    path: Path,
    expected_type: type[Targets] | type[Snapshot] | type[Timestamp],
) -> int:
    metadata = Metadata.from_bytes(path.read_bytes())
    assert isinstance(metadata.signed, expected_type)
    return metadata.signed.version
