"""通用制品发布流水线单元测试。"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import httpx
import pytest
from pydantic import ValidationError

from src.application.artifact_release_orchestrator import ArtifactReleaseOrchestrator
from src.application.ports.artifact_release_port import ArtifactHealthCallback
from src.core.artifact_release_contract.artifact_contract import (
    ArtifactActivationRecord,
    ArtifactActivationState,
    ArtifactArchitecture,
    ArtifactChannel,
    ArtifactIdentity,
    ArtifactPlatform,
    ArtifactReleaseEnvelope,
    ArtifactReleaseStep,
    ArtifactSignatureDetail,
    ArtifactVerificationResult,
    TufTargetMetadata,
)
from src.core.artifact_release_contract.runtime_contract import ArtifactReleaseRuntimeSettings
from src.infrastructure.artifact_release.composite_verifier import CompositeArtifactVerifier
from src.infrastructure.artifact_release.digest_verifier import Sha256ArtifactVerifier
from src.infrastructure.artifact_release.rollout_policy import ArtifactRolloutPolicy
from src.infrastructure.artifact_release.safe_downloader import SafeArtifactDownloader
from src.infrastructure.artifact_release.settings_loader import ArtifactReleaseSettingsLoader
from src.infrastructure.artifact_release.signed_activation import (
    ACTIVE_VERSION_FILE_NAME,
    AtomicArtifactActivationAdapter,
)
from src.infrastructure.artifact_release.staging_store import LocalArtifactStagingStore
from src.infrastructure.artifact_release.tuf_catalog_adapter import (
    AllowlistedTufFetcher,
    TufArtifactCatalogAdapter,
)
from src.infrastructure.artifact_release.windows_authenticode_verifier import (
    WindowsAuthenticodeVerifier,
)
from src.infrastructure.codex_agent.agent_release_runtime import CodexAgentReleaseRuntime
from src.infrastructure.codex_agent.codex_agent_update_coordinator import (
    AGENT_ARTIFACT_NAME,
    CODEX_ARTIFACT_NAME,
    CodexAgentUpdateCoordinator,
)

ARTIFACT_CONTENT = b"release"
ARTIFACT_DIGEST = hashlib.sha256(ARTIFACT_CONTENT).hexdigest()
TEST_SIGNER_SHA256 = "c" * 64
REPOSITORY_HOST = "updates.acme.dev"
REPOSITORY_URL = f"https://{REPOSITORY_HOST}"
TARGET_URL = f"{REPOSITORY_URL}/targets/agent.bin"


class ArtifactHttpTransport(httpx.AsyncBaseTransport):
    """提供下载大小和长度边界响应。"""

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/declared-too-large":
            return httpx.Response(200, headers={"content-length": "9"}, content=b"oversized")
        if request.url.path == "/stream-too-large":
            return httpx.Response(200, content=b"oversized")
        if request.url.path == "/wrong-length":
            return httpx.Response(200, content=ARTIFACT_CONTENT)
        return httpx.Response(
            200,
            headers={"content-length": str(len(ARTIFACT_CONTENT))},
            content=ARTIFACT_CONTENT,
        )


class TufHttpTransport(httpx.BaseTransport):
    """提供 TUF fetcher 的重定向和固定主机响应。"""

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/redirect":
            return httpx.Response(
                302,
                headers={"location": "https://other.acme.dev/target"},
                request=request,
            )
        return httpx.Response(200, content=ARTIFACT_CONTENT, request=request)


@dataclass(slots=True)
class StaticArtifactCatalog:
    """返回固定受审发布信封。"""

    envelope: ArtifactReleaseEnvelope

    async def resolve(self, identity: ArtifactIdentity) -> ArtifactReleaseEnvelope:
        assert identity == self.envelope.identity
        return self.envelope


@dataclass(slots=True)
class StaticArtifactDownloader:
    """返回固定制品正文。"""

    content: bytes

    async def download(self, envelope: ArtifactReleaseEnvelope, target_url: str) -> bytes:
        assert envelope.identity.digest_sha256 == ARTIFACT_DIGEST
        assert target_url == TARGET_URL
        return self.content


@dataclass(slots=True)
class RecordingArtifactVerifier:
    """记录摘要验证调用。"""

    verified: bool = False

    async def verify(
        self,
        envelope: ArtifactReleaseEnvelope,
        content: bytes,
    ) -> ArtifactVerificationResult:
        self.verified = True
        return ArtifactVerificationResult(
            identity=envelope.identity,
            digest_verified=content == ARTIFACT_CONTENT,
            signature_verified=True,
            signature=envelope.signature,
        )


@dataclass(slots=True)
class RecordingArtifactStaging:
    """记录暂存与清理操作。"""

    root: Path
    cleaned: bool = False

    async def stage(self, identity: ArtifactIdentity, content: bytes) -> Path:
        path = self.root / identity.version / identity.artifact_name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    async def cleanup(self, identity: ArtifactIdentity) -> None:
        self.cleaned = identity.version == "1.2.3"


@dataclass(slots=True)
class RecordingArtifactActivation:
    """记录激活、提交和回滚状态。"""

    states: list[ArtifactActivationState] = field(default_factory=list)

    async def activate(
        self,
        identity: ArtifactIdentity,
        staged_path: Path,
    ) -> ArtifactActivationRecord:
        self.states.append(ArtifactActivationState.ACTIVE)
        return ArtifactActivationRecord(
            identity=identity,
            state=ArtifactActivationState.ACTIVE,
            staged_path=staged_path,
            activated_at=datetime.now(UTC),
        )

    async def commit(self, record: ArtifactActivationRecord) -> ArtifactActivationRecord:
        self.states.append(ArtifactActivationState.COMMITTED)
        return record.model_copy(update={"state": ArtifactActivationState.COMMITTED})

    async def rollback(self, record: ArtifactActivationRecord) -> ArtifactActivationRecord:
        self.states.append(ArtifactActivationState.ROLLED_BACK)
        return record.model_copy(update={"state": ArtifactActivationState.ROLLED_BACK})


@dataclass(slots=True)
class FakeTufTargetInfo:
    """模拟 python-tuf 已验证目标摘要。"""

    length: int = len(ARTIFACT_CONTENT)
    hashes: dict[str, str] = field(default_factory=lambda: {"sha256": ARTIFACT_DIGEST})
    custom: dict[str, str] = field(default_factory=lambda: {"channel": "stable"})


class FakeTufUpdater:
    """记录 TUF refresh 并返回固定 target。"""

    refreshed = False
    return_missing = False

    def __init__(
        self,
        *,
        metadata_dir: str,
        target_dir: str,
        metadata_base_url: str,
        target_base_url: str,
        fetcher: object,
        bootstrap: bytes,
    ) -> None:
        assert metadata_dir.endswith("metadata")
        assert target_dir.endswith("targets")
        assert metadata_base_url.endswith("/metadata/")
        assert target_base_url.endswith("/targets/")
        assert fetcher is not None
        assert bootstrap == b"trusted-root"

    def refresh(self) -> None:
        FakeTufUpdater.refreshed = True

    def get_targetinfo(self, target_path: str) -> FakeTufTargetInfo | None:
        assert target_path == "agent/windows/x86_64/stable/1.2.3"
        return None if self.return_missing else FakeTufTargetInfo()


class TestArtifactReleasePipelineUnit:
    """验证制品契约、下载、校验、暂存、激活和更新协调。"""

    def test_contract_and_runtime_settings_should_reject_untrusted_values(
        self,
        tmp_path: Path,
    ) -> None:
        identity = self._identity()
        settings = self._settings(tmp_path)

        assert identity.platform is ArtifactPlatform.WINDOWS
        assert settings.repository_url == REPOSITORY_URL
        assert settings.repository_host_allowlist == (REPOSITORY_HOST,)
        with pytest.raises(ValidationError):
            ArtifactIdentity(
                artifact_name="agent",
                platform=ArtifactPlatform.WINDOWS,
                architecture=ArtifactArchitecture.X86_64,
                channel=ArtifactChannel.STABLE,
                version="1.2.3",
                digest_sha256="short",
            )
        with pytest.raises(ValidationError, match="HTTPS"):
            self._settings(tmp_path, repository_url="http://updates.example.com")

    def test_tuf_fetcher_should_reject_redirects_and_unallowlisted_hosts(self) -> None:
        client = httpx.Client(transport=TufHttpTransport(), follow_redirects=False)
        fetcher = AllowlistedTufFetcher(
            host_allowlist=(REPOSITORY_HOST,),
            timeout_seconds=30,
            client=client,
        )
        try:
            assert b"".join(fetcher.fetch(f"{REPOSITORY_URL}/target")) == ARTIFACT_CONTENT
            with pytest.raises(Exception, match="redirects are forbidden"):
                list(fetcher.fetch(f"{REPOSITORY_URL}/redirect"))
            with pytest.raises(Exception, match="outside the repository allowlist"):
                list(fetcher.fetch("https://other.acme.dev/target"))
            with pytest.raises(Exception, match="outside the repository allowlist"):
                list(fetcher.fetch(f"http://{REPOSITORY_HOST}/target"))
        finally:
            fetcher.close()

    @pytest.mark.asyncio
    async def test_digest_and_composite_verifier_should_enforce_digest_and_signature(self) -> None:
        identity = self._identity()
        signature = self._signature()
        target = self._target()
        signed = ArtifactReleaseEnvelope(
            identity=identity,
            signature=signature,
            tuf_target=target,
        )
        unsigned = signed.model_copy(update={"signature": None})
        digest_verifier = Sha256ArtifactVerifier()

        digest_result = await digest_verifier.verify(signed, ARTIFACT_CONTENT)
        signature_verifier = RecordingArtifactVerifier()
        composite = CompositeArtifactVerifier(digest_verifier, signature_verifier)
        composite_result = await composite.verify(
            signed,
            ARTIFACT_CONTENT,
        )
        unsigned_result = await composite.verify(unsigned, ARTIFACT_CONTENT)

        assert digest_result.digest_verified is True
        assert digest_result.signature_verified is True
        assert composite_result.signature_verified is True
        assert unsigned_result.signature_verified is True
        with pytest.raises(ValueError, match="SHA-256"):
            await digest_verifier.verify(signed, b"tampered")
        with pytest.raises(ValueError, match="TUF"):
            await digest_verifier.verify(
                signed.model_copy(
                    update={
                        "tuf_target": target.model_copy(update={"hashes": {"sha256": "0" * 64}})
                    }
                ),
                ARTIFACT_CONTENT,
            )
        with pytest.raises(ValueError, match="TUF"):
            await composite.verify(
                signed.model_copy(update={"tuf_target": None}),
                ARTIFACT_CONTENT,
            )

    @pytest.mark.asyncio
    async def test_safe_downloader_should_enforce_allowlist_size_and_tuf_length(
        self,
        tmp_path: Path,
    ) -> None:
        settings = self._settings(tmp_path, max_download_bytes=8)
        envelope = self._envelope()
        async with httpx.AsyncClient(transport=ArtifactHttpTransport()) as client:
            downloader = SafeArtifactDownloader(client=client, settings=settings)

            content = await downloader.download(envelope, TARGET_URL)

            assert content == ARTIFACT_CONTENT
            with pytest.raises(ValueError, match="allowlist"):
                await downloader.download(envelope, "http://updates.example.com/agent")
            with pytest.raises(ValueError, match="allowlist"):
                await downloader.download(envelope, "https://untrusted.example/agent")
            with pytest.raises(ValueError, match="TUF"):
                await downloader.download(
                    envelope.model_copy(update={"tuf_target": None}),
                    TARGET_URL,
                )
            with pytest.raises(ValueError, match="大小"):
                await downloader.download(envelope, f"{REPOSITORY_URL}/declared-too-large")
            with pytest.raises(ValueError, match="大小"):
                await downloader.download(envelope, f"{REPOSITORY_URL}/stream-too-large")
            with pytest.raises(ValueError, match="长度"):
                await downloader.download(
                    envelope.model_copy(
                        update={"tuf_target": self._target(length=len(ARTIFACT_CONTENT) + 1)}
                    ),
                    f"{REPOSITORY_URL}/wrong-length",
                )

    @pytest.mark.asyncio
    async def test_staging_and_activation_should_commit_and_restore_previous_version(
        self,
        tmp_path: Path,
    ) -> None:
        identity = self._identity()
        staging = LocalArtifactStagingStore(staging_root=tmp_path / "staging")
        activation = AtomicArtifactActivationAdapter(root=tmp_path / "activation")

        staged_path = await staging.stage(identity, ARTIFACT_CONTENT)
        first = await activation.activate(identity, staged_path)
        committed = await activation.commit(first)
        first_rollback = await activation.rollback(first)
        assert first_rollback.state is ArtifactActivationState.ROLLED_BACK
        assert not (tmp_path / "activation" / ACTIVE_VERSION_FILE_NAME).exists()

        first = await activation.activate(identity, staged_path)
        committed = await activation.commit(first)

        second_identity = identity.model_copy(update={"version": "1.2.4"})
        second_path = await staging.stage(second_identity, ARTIFACT_CONTENT)
        second = await activation.activate(second_identity, second_path)
        rolled_back = await activation.rollback(second)

        assert staged_path.read_bytes() == ARTIFACT_CONTENT
        assert committed.state is ArtifactActivationState.COMMITTED
        assert rolled_back.state is ArtifactActivationState.ROLLED_BACK
        active_payload = json.loads(
            (tmp_path / "activation" / ACTIVE_VERSION_FILE_NAME).read_text("utf-8")
        )
        assert active_payload["version"] == identity.version
        await staging.cleanup(identity)
        assert not staged_path.exists()

        missing_activation = AtomicArtifactActivationAdapter(root=tmp_path / "missing")
        with pytest.raises(RuntimeError, match="没有可回滚"):
            await missing_activation.rollback(first)

    @pytest.mark.asyncio
    async def test_orchestrator_should_commit_healthy_and_rollback_unhealthy_release(
        self,
        tmp_path: Path,
    ) -> None:
        identity = self._identity()
        verifier = RecordingArtifactVerifier()
        staging = RecordingArtifactStaging(tmp_path)
        activation = RecordingArtifactActivation()
        orchestrator = ArtifactReleaseOrchestrator(
            catalog=StaticArtifactCatalog(self._envelope()),
            downloader=StaticArtifactDownloader(ARTIFACT_CONTENT),
            verifier=verifier,
            staging=staging,
            activation=activation,
        )

        healthy = await orchestrator.execute(
            identity=identity,
            target_url=TARGET_URL,
            health_check=cast(ArtifactHealthCallback, self._healthy),
        )
        unhealthy = await orchestrator.execute(
            identity=identity,
            target_url=TARGET_URL,
            health_check=cast(ArtifactHealthCallback, self._unhealthy),
        )

        assert verifier.verified is True
        assert healthy.completed_steps == (
            ArtifactReleaseStep.RESOLVE,
            ArtifactReleaseStep.DOWNLOAD,
            ArtifactReleaseStep.VERIFY,
            ArtifactReleaseStep.STAGE,
            ArtifactReleaseStep.ACTIVATE,
            ArtifactReleaseStep.HEALTH,
            ArtifactReleaseStep.COMMIT,
        )
        assert healthy.activation.state is ArtifactActivationState.COMMITTED
        assert unhealthy.rollback_performed is True
        assert unhealthy.failure_code == "artifact.health_failed"
        assert unhealthy.activation.state is ArtifactActivationState.ROLLED_BACK

    @pytest.mark.asyncio
    async def test_orchestrator_should_rollback_when_health_check_raises(
        self,
        tmp_path: Path,
    ) -> None:
        activation = RecordingArtifactActivation()
        orchestrator = ArtifactReleaseOrchestrator(
            catalog=StaticArtifactCatalog(self._envelope()),
            downloader=StaticArtifactDownloader(ARTIFACT_CONTENT),
            verifier=RecordingArtifactVerifier(),
            staging=RecordingArtifactStaging(tmp_path),
            activation=activation,
        )

        async def failed_health_check(_record: ArtifactActivationRecord) -> bool:
            raise TimeoutError("doctor timed out")

        with pytest.raises(TimeoutError, match="doctor timed out"):
            await orchestrator.execute(
                identity=self._identity(),
                target_url=TARGET_URL,
                health_check=failed_health_check,
            )

        assert activation.states[-1] is ArtifactActivationState.ROLLED_BACK

    @pytest.mark.asyncio
    async def test_rollout_and_coordinator_should_select_agent_and_codex_targets(
        self,
        tmp_path: Path,
    ) -> None:
        identity = self._identity()
        policy = ArtifactRolloutPolicy()
        assert policy.is_allowed(
            identity=identity,
            rollout_subject_digest="subject",
            rollout_percent=100,
            paused=False,
            forced=False,
        )
        assert policy.is_allowed(
            identity=identity,
            rollout_subject_digest="subject",
            rollout_percent=0,
            paused=False,
            forced=True,
        )
        assert not policy.is_allowed(
            identity=identity,
            rollout_subject_digest="subject",
            rollout_percent=100,
            paused=True,
            forced=True,
        )
        assert not policy.is_allowed(
            identity=identity,
            rollout_subject_digest="subject",
            rollout_percent=0,
            paused=False,
            forced=False,
        )
        beta = identity.model_copy(update={"channel": ArtifactChannel.BETA})
        bucket_result = policy.is_allowed(
            identity=beta,
            rollout_subject_digest="subject",
            rollout_percent=50,
            paused=False,
            forced=False,
        )
        assert isinstance(bucket_result, bool)

        coordinator = self._coordinator(tmp_path, policy)
        agent = await coordinator.update_agent(
            version=identity.version,
            digest_sha256=identity.digest_sha256,
            target_url=TARGET_URL,
            rollout_percent=100,
            rollout_subject_digest="subject",
            forced=False,
            health_check=cast(ArtifactHealthCallback, self._healthy),
        )
        codex = await coordinator.update_codex(
            version=identity.version,
            digest_sha256=identity.digest_sha256,
            target_url=TARGET_URL,
            health_check=cast(ArtifactHealthCallback, self._healthy),
        )

        assert agent.identity.artifact_name == AGENT_ARTIFACT_NAME
        assert codex.identity.artifact_name == CODEX_ARTIFACT_NAME
        with pytest.raises(PermissionError, match="灰度桶"):
            await coordinator.update_agent(
                version=identity.version,
                digest_sha256=identity.digest_sha256,
                target_url=TARGET_URL,
                rollout_percent=0,
                rollout_subject_digest="subject",
                forced=False,
                health_check=cast(ArtifactHealthCallback, self._healthy),
            )

    @pytest.mark.asyncio
    async def test_tuf_settings_authenticode_and_runtime_adapters_should_delegate(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import src.infrastructure.artifact_release.tuf_catalog_adapter as tuf_module
        import src.infrastructure.artifact_release.windows_authenticode_verifier as signer_module

        trusted_root = tmp_path / "root.json"
        trusted_root.write_bytes(b"trusted-root")
        settings = self._settings(tmp_path, trusted_root_path=str(trusted_root))
        monkeypatch.setattr(tuf_module, "Updater", FakeTufUpdater)
        adapter = TufArtifactCatalogAdapter(settings=settings)

        with pytest.raises(ValueError, match="规范相对路径"):
            await adapter.read_target("../codex-agent-release.json")

        envelope = await adapter.resolve(self._identity())

        assert FakeTufUpdater.refreshed is True
        assert envelope.tuf_target is not None
        assert envelope.tuf_target.hashes["sha256"] == ARTIFACT_DIGEST
        FakeTufUpdater.return_missing = True
        try:
            with pytest.raises(FileNotFoundError, match="未找到"):
                await adapter.resolve(self._identity())
        finally:
            FakeTufUpdater.return_missing = False

        config_path = tmp_path / "artifact.toml"
        config_path.write_text(
            "\n".join(
                (
                    "[runtime]",
                    'trusted_root_path = "root.json"',
                    f'repository_url = "{REPOSITORY_URL}/"',
                    f'repository_host_allowlist = ["{REPOSITORY_HOST}"]',
                    f'authenticode_signer_sha256_allowlist = ["{TEST_SIGNER_SHA256}"]',
                    "max_download_bytes = 1024",
                    "request_timeout_seconds = 30",
                    'staging_root = "staging"',
                    "retained_versions = 2",
                    "health_timeout_seconds = 30",
                    "rollback_budget = 1",
                )
            ),
            encoding="utf-8",
        )
        loaded = ArtifactReleaseSettingsLoader().load(config_path)
        assert loaded.repository_url == REPOSITORY_URL
        empty_config = tmp_path / "empty.toml"
        empty_config.write_text("enabled = true", encoding="utf-8")
        with pytest.raises(ValueError, match="runtime"):
            ArtifactReleaseSettingsLoader().load(empty_config)

        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps(
                {
                    "Status": "Valid",
                    "Subject": "CN=Release",
                    "SignerSha256": TEST_SIGNER_SHA256.upper(),
                }
            ),
            stderr="",
        )
        monkeypatch.setattr(signer_module.subprocess, "run", lambda *args, **kwargs: completed)
        signature = await WindowsAuthenticodeVerifier(
            allowed_signer_sha256=(TEST_SIGNER_SHA256,)
        ).verify(tmp_path / "agent.exe")
        assert signature.method == "authenticode"
        assert signature.signer_sha256 == TEST_SIGNER_SHA256
        mismatched = completed.__class__(
            args=[],
            returncode=0,
            stdout=json.dumps(
                {
                    "Status": "Valid",
                    "Subject": "CN=Other",
                    "SignerSha256": "d" * 64,
                }
            ),
            stderr="",
        )
        monkeypatch.setattr(signer_module.subprocess, "run", lambda *args, **kwargs: mismatched)
        with pytest.raises(ValueError, match="允许列表"):
            await WindowsAuthenticodeVerifier(allowed_signer_sha256=(TEST_SIGNER_SHA256,)).verify(
                tmp_path / "agent.exe"
            )
        invalid = completed.__class__(
            args=[],
            returncode=0,
            stdout=json.dumps(
                {
                    "Status": "NotSigned",
                    "Subject": "",
                    "SignerSha256": "",
                }
            ),
            stderr="",
        )
        monkeypatch.setattr(signer_module.subprocess, "run", lambda *args, **kwargs: invalid)
        with pytest.raises(ValueError, match="Authenticode"):
            await WindowsAuthenticodeVerifier(allowed_signer_sha256=(TEST_SIGNER_SHA256,)).verify(
                tmp_path / "agent.exe"
            )

        runtime = CodexAgentReleaseRuntime.build(settings)
        try:
            assert isinstance(runtime.coordinator, CodexAgentUpdateCoordinator)
        finally:
            await runtime.close()

    def _identity(self, *, artifact_name: str = "agent") -> ArtifactIdentity:
        return ArtifactIdentity(
            artifact_name=artifact_name,
            platform=ArtifactPlatform.WINDOWS,
            architecture=ArtifactArchitecture.X86_64,
            channel=ArtifactChannel.STABLE,
            version="1.2.3",
            digest_sha256=ARTIFACT_DIGEST,
        )

    def _signature(self) -> ArtifactSignatureDetail:
        return ArtifactSignatureDetail(
            method="authenticode",
            signer_subject="CN=Release",
            verified_at=datetime.now(UTC),
        )

    def _target(self, *, length: int = len(ARTIFACT_CONTENT)) -> TufTargetMetadata:
        return TufTargetMetadata(
            target_path="targets/agent.bin",
            length=length,
            hashes={"sha256": ARTIFACT_DIGEST},
        )

    def _envelope(self, *, artifact_name: str = "agent") -> ArtifactReleaseEnvelope:
        return ArtifactReleaseEnvelope(
            identity=self._identity(artifact_name=artifact_name),
            signature=self._signature(),
            tuf_target=self._target(),
        )

    def _settings(
        self,
        tmp_path: Path,
        *,
        repository_url: str = REPOSITORY_URL,
        trusted_root_path: str | None = None,
        max_download_bytes: int = 1_024,
    ) -> ArtifactReleaseRuntimeSettings:
        return ArtifactReleaseRuntimeSettings(
            trusted_root_path=trusted_root_path or str(tmp_path / "root.json"),
            repository_url=repository_url,
            repository_host_allowlist=(REPOSITORY_HOST,),
            authenticode_signer_sha256_allowlist=(TEST_SIGNER_SHA256,),
            max_download_bytes=max_download_bytes,
            request_timeout_seconds=30,
            staging_root=str(tmp_path / "staging"),
            retained_versions=2,
            health_timeout_seconds=30,
            rollback_budget=1,
        )

    def _coordinator(
        self,
        tmp_path: Path,
        policy: ArtifactRolloutPolicy,
    ) -> CodexAgentUpdateCoordinator:
        agent_envelope = self._envelope(artifact_name=AGENT_ARTIFACT_NAME)
        codex_envelope = self._envelope(artifact_name=CODEX_ARTIFACT_NAME)

        @dataclass(slots=True)
        class TargetCatalog:
            """按 artifact_name 返回对应信封。"""

            async def resolve(self, identity: ArtifactIdentity) -> ArtifactReleaseEnvelope:
                return (
                    agent_envelope
                    if identity.artifact_name == AGENT_ARTIFACT_NAME
                    else codex_envelope
                )

        return CodexAgentUpdateCoordinator(
            orchestrator=ArtifactReleaseOrchestrator(
                catalog=TargetCatalog(),
                downloader=StaticArtifactDownloader(ARTIFACT_CONTENT),
                verifier=RecordingArtifactVerifier(),
                staging=RecordingArtifactStaging(tmp_path),
                activation=RecordingArtifactActivation(),
            ),
            rollout_policy=policy,
        )

    @staticmethod
    async def _healthy(_record: ArtifactActivationRecord) -> bool:
        return True

    @staticmethod
    async def _unhealthy(_record: ArtifactActivationRecord) -> bool:
        return False
