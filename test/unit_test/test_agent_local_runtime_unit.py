"""Agent 本地 doctor、设备授权和 DPAPI 存储单元测试。"""

from __future__ import annotations

import base64
import hashlib
import logging
import sqlite3
import ssl
import subprocess
import tomllib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import certifi
import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from src.cli.run_codex_host_agent import CodexHostAgentCli
from src.core.codex_contract.agent_runtime_health_contract import (
    AgentDoctorCheck,
    AgentDoctorCheckState,
    AgentDoctorExitCode,
)
from src.core.codex_contract.connection_session_contract import CodexConnectionProtocolVersion
from src.core.codex_contract.device_authorization_contract import (
    DeviceAuthorizationCreateRequestEnvelope,
    DeviceAuthorizationEnvelope,
    DeviceAuthorizationHeader,
    DeviceAuthorizationIssuedDetail,
    DeviceAuthorizationState,
    DeviceAuthorizationStatusDetail,
)
from src.core.http_contract.outbound_http_client_contract import AsyncHttpClientDetail
from src.infrastructure.codex_agent.agent_command_journal import AgentCommandJournal
from src.infrastructure.codex_agent.agent_configuration import (
    AgentBootstrapConnectionSettings,
    AgentBootstrapSettings,
    AgentProcessSettings,
    AgentProtocolSettings,
    AgentWorkspaceSettings,
    CodexHostAgentSettings,
)
from src.infrastructure.codex_agent.agent_connection_ticket_provider import (
    AgentConnectionTicketProvider,
)
from src.infrastructure.codex_agent.agent_control_channel import AgentControlChannel
from src.infrastructure.codex_agent.agent_deployment_profile import AgentDeploymentProfile
from src.infrastructure.codex_agent.agent_doctor import AgentDoctor
from src.infrastructure.codex_agent.agent_secret_store import (
    AgentSecretNotFoundError,
    WindowsAgentSecretStore,
)
from src.infrastructure.codex_agent.agent_setup import (
    DEVICE_AUTHORIZATION_CREATE_PATH,
    DEVICE_AUTHORIZATION_POLL_PATH,
    CodexAgentSetupUsecase,
    WindowsEnrollmentUi,
)
from src.infrastructure.codex_agent.agent_workspace_registry import AgentWorkspaceRegistry
from src.infrastructure.codex_agent.windows_dpapi_device_key_store import (
    PRIVATE_KEY_LENGTH,
    WindowsCurrentUserAclEnforcer,
    WindowsCurrentUserDpapi,
    WindowsDpapiDeviceKeyStore,
)
from src.infrastructure.resource_slot.shared_async_http_client import SharedAsyncHttpClient

FROZEN_SCHEMA_DIGEST = "a" * 64
DEVICE_CODE = "device-code-0123456789abcdef0123456789abcdef"
USER_CODE = "ABCD-EFGH"
TEST_AGENT_VERSION = "0.1.0"


class InMemoryDeviceKeyStore:
    """使用真实 Ed25519 原语的测试密钥存储。"""

    def __init__(self) -> None:
        self._keys: dict[UUID, Ed25519PrivateKey] = {}
        self.deleted: list[UUID] = []

    def generate(self, key_id: UUID) -> bytes:
        key = Ed25519PrivateKey.generate()
        self._keys[key_id] = key
        return key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)

    def read_public_key(self, key_id: UUID) -> bytes:
        return self._keys[key_id].public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)

    def sign(self, key_id: UUID, message: bytes) -> bytes:
        return self._keys[key_id].sign(message)

    def delete(self, key_id: UUID) -> None:
        self._keys.pop(key_id, None)
        self.deleted.append(key_id)


class RecordingEnrollmentUi(WindowsEnrollmentUi):
    """记录展示内容而不打开系统浏览器。"""

    def __init__(self) -> None:
        self.verification_uri: str | None = None
        self.user_code: str | None = None
        self.fingerprint: str | None = None

    def show(self, *, verification_uri: str, user_code: str, fingerprint: str) -> None:
        self.verification_uri = verification_uri
        self.user_code = user_code
        self.fingerprint = fingerprint


class RecordingAclEnforcer(WindowsCurrentUserAclEnforcer):
    """记录 ACL 目标。"""

    def __init__(self) -> None:
        self.paths: list[Path] = []

    def enforce(self, path: Path) -> None:
        self.paths.append(path)


class PassthroughDpapi(WindowsCurrentUserDpapi):
    """为测试保留 DPAPI 调用边界但不依赖 Windows。"""

    def __init__(self, *, invalid_length: bool = False) -> None:
        self.invalid_length = invalid_length

    def protect(self, value: bytes) -> bytes:
        return b"protected:" + value

    def unprotect(self, value: bytes) -> bytes:
        if self.invalid_length:
            return b"short"
        return value.removeprefix(b"protected:")


class DeviceAuthorizationTransport(httpx.AsyncBaseTransport):
    """提供 issued、slow_down 和终态授权响应。"""

    def __init__(self, *, terminal_state: DeviceAuthorizationState) -> None:
        self.terminal_state = terminal_state
        self.enrollment_id = uuid4()
        self.key_id: UUID | None = None
        self.poll_count = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == DEVICE_AUTHORIZATION_CREATE_PATH:
            payload = self._decode_request(request)
            self.key_id = payload.detail.key_id
            return httpx.Response(200, json=self._issued().model_dump(mode="json"))
        if request.url.path == DEVICE_AUTHORIZATION_POLL_PATH:
            self.poll_count += 1
            if self.poll_count == 1:
                return httpx.Response(httpx.codes.TOO_MANY_REQUESTS)
            return httpx.Response(200, json=self._status().model_dump(mode="json"))
        return httpx.Response(404)

    def _decode_request(self, request: httpx.Request) -> DeviceAuthorizationCreateRequestEnvelope:
        return DeviceAuthorizationCreateRequestEnvelope.model_validate_json(request.content)

    def _issued(self) -> DeviceAuthorizationEnvelope:
        return DeviceAuthorizationEnvelope(
            header=DeviceAuthorizationHeader(enrollment_id=self.enrollment_id),
            detail=DeviceAuthorizationIssuedDetail(
                device_code=DEVICE_CODE,
                user_code=USER_CODE,
                verification_uri="https://control.example/device",
                interval_seconds=1,
                expires_at=datetime.now(UTC) + timedelta(minutes=5),
            ),
        )

    def _status(self) -> DeviceAuthorizationEnvelope:
        assert self.key_id is not None
        return DeviceAuthorizationEnvelope(
            header=DeviceAuthorizationHeader(enrollment_id=self.enrollment_id),
            detail=DeviceAuthorizationStatusDetail(
                state=self.terminal_state,
                display_name="Workstation",
                platform="windows",
                public_key_fingerprint="b" * 64,
                interval_seconds=1,
                expires_at=datetime.now(UTC) + timedelta(minutes=5),
                host_id=uuid4()
                if self.terminal_state is DeviceAuthorizationState.APPROVED
                else None,
                key_id=self.key_id,
            ),
        )


class ReadableDeviceKeyStore:
    """为 doctor 提供可选读取失败。"""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    def generate(self, key_id: UUID) -> bytes:
        raise AssertionError(f"doctor 不应生成密钥：{key_id}")

    def read_public_key(self, key_id: UUID) -> bytes:
        if self.fail:
            raise KeyError(key_id)
        return b"p" * 32

    def sign(self, key_id: UUID, message: bytes) -> bytes:
        raise AssertionError(f"doctor 不应签名：{key_id}:{len(message)}")

    def delete(self, key_id: UUID) -> None:
        raise AssertionError(f"doctor 不应删除密钥：{key_id}")


class TestAgentLocalRuntimeUnit:
    """覆盖 Agent 本地资源生命周期和失败收敛。"""

    def test_setup_cli_should_not_load_missing_agent_config(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        config_path = tmp_path / "agent.toml"
        workspace_root = tmp_path / "workspace"
        workspace_root.mkdir()
        cli = CodexHostAgentCli()

        async def run_setup(
            *,
            config_path: Path,
            api_url: str,
            websocket_url: str,
            verification_url: str | None,
            display_name: str,
            workspace_root: Path,
            workspace_key: str,
            workspace_name: str,
            agent_version: str,
            codex_version: str,
            codex_binary: str,
            schema_digest: str,
            development_ca_certificate_path: Path | None,
        ) -> int:
            assert config_path == tmp_path / "agent.toml"
            assert api_url == "https://control.example"
            assert websocket_url == "wss://control.example/internal/codex-agents/connect"
            assert verification_url is None
            assert display_name == "Workstation"
            assert workspace_root == tmp_path / "workspace"
            assert workspace_key == "work"
            assert workspace_name == "Workspace"
            assert agent_version == TEST_AGENT_VERSION
            assert codex_version == "0.145.0"
            assert codex_binary == "C:\\tools\\codex-0.145.0.exe"
            assert schema_digest == FROZEN_SCHEMA_DIGEST
            assert development_ca_certificate_path is None
            return 0

        def reject_config_load(_config_path: Path) -> CodexHostAgentSettings:
            raise AssertionError("setup首次执行前不得读取尚未生成的配置。")

        monkeypatch.setattr(cli, "run_setup", run_setup)
        monkeypatch.setattr(cli, "load_settings", reject_config_load)

        exit_code = cli.execute(
            [
                "--config",
                str(config_path),
                "setup",
                "--api-url",
                "https://control.example",
                "--websocket-url",
                "wss://control.example/internal/codex-agents/connect",
                "--display-name",
                "Workstation",
                "--workspace-root",
                str(workspace_root),
                "--workspace-key",
                "work",
                "--workspace-name",
                "Workspace",
                "--codex-version",
                "0.145.0",
                "--codex-binary",
                "C:\\tools\\codex-0.145.0.exe",
                "--schema-digest",
                FROZEN_SCHEMA_DIGEST,
            ]
        )

        assert exit_code == 0

    @pytest.mark.asyncio
    async def test_development_certificate_should_reach_http_transport_and_wss_client(
        self,
        tmp_path: Path,
    ) -> None:
        """开发 CA 必须同时进入 HTTPS ticket 与 WSS，而非依赖进程环境变量。"""

        certificate_path = Path(certifi.where()).resolve()
        context = ssl.create_default_context(cafile=str(certificate_path))
        http_resource = SharedAsyncHttpClient(
            AsyncHttpClientDetail(
                timeout_seconds=1,
                max_connections=1,
                max_keepalive_connections=1,
            ),
            tls_context=context,
        )
        try:
            pool = http_resource._transport._pool  # noqa: SLF001
            assert getattr(pool, "_ssl_context") is context
        finally:
            await http_resource.close()

        settings = self._settings(tmp_path).model_copy(
            update={
                "agent": self._settings(tmp_path).agent.model_copy(
                    update={
                        "deployment_profile": AgentDeploymentProfile.DEVELOPMENT,
                        "development_ca_certificate_path": certificate_path,
                    }
                )
            }
        )
        journal = AgentCommandJournal(tmp_path / "agent-events.sqlite")
        try:
            channel = AgentControlChannel(
                settings=settings,
                secret_store=WindowsAgentSecretStore(),
                connection_ticket_provider=None,
                workspace_registry=AgentWorkspaceRegistry(
                    [workspace.to_definition() for workspace in settings.workspaces]
                ),
                journal=journal,
                logger=logging.getLogger("agent-development-tls-test"),
            )
            websocket_context = channel._tls_context  # noqa: SLF001
        finally:
            journal.close()

        assert isinstance(websocket_context, ssl.SSLContext)
        assert websocket_context.verify_mode is ssl.CERT_REQUIRED
        assert websocket_context.check_hostname is True

    @pytest.mark.asyncio
    async def test_run_v2_should_create_signed_connection_ticket_provider(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import src.cli.run_codex_host_agent as cli_module

        providers: list[AgentConnectionTicketProvider | None] = []

        class RecordingAgentControlChannel:
            def __init__(
                self,
                *,
                settings: CodexHostAgentSettings,
                secret_store: WindowsAgentSecretStore,
                connection_ticket_provider: AgentConnectionTicketProvider | None,
                workspace_registry: AgentWorkspaceRegistry,
                journal: AgentCommandJournal,
                logger: logging.Logger,
            ) -> None:
                assert settings.protocol.agent_schema_version is CodexConnectionProtocolVersion.V2
                assert isinstance(secret_store, WindowsAgentSecretStore)
                assert isinstance(workspace_registry, AgentWorkspaceRegistry)
                assert isinstance(journal, AgentCommandJournal)
                assert logger.name == "codex_host_agent"
                providers.append(connection_ticket_provider)

            async def run(self) -> None:
                return None

        monkeypatch.setattr(cli_module, "AgentControlChannel", RecordingAgentControlChannel)

        async def skip_startup_update(
            _self: CodexHostAgentCli,
            **_kwargs: object,
        ) -> int | None:
            return None

        monkeypatch.setattr(CodexHostAgentCli, "_apply_startup_update", skip_startup_update)

        bootstrap = AgentBootstrapSettings(
            deployment_state="configured",
            connection=AgentBootstrapConnectionSettings(
                api_url="https://control.acme.dev",
                websocket_url="wss://control.acme.dev/internal/codex-agents/connect",
                verification_url="https://control.acme.dev/codex/verify-device",
                website_url="https://control.acme.dev",
            ),
            agent_version=TEST_AGENT_VERSION,
            expected_codex_version="0.145.0",
            app_server_schema_digest=FROZEN_SCHEMA_DIGEST,
        )

        await CodexHostAgentCli().run_agent(
            self._settings(tmp_path),
            config_path=tmp_path / "agent.toml",
            bootstrap_path=tmp_path / "bootstrap.toml",
            bootstrap=bootstrap,
        )

        assert len(providers) == 1
        assert isinstance(providers[0], AgentConnectionTicketProvider)

    @pytest.mark.asyncio
    async def test_setup_should_poll_approval_write_config_and_preserve_device_key(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import src.infrastructure.codex_agent.agent_setup as setup_module

        transport = DeviceAuthorizationTransport(terminal_state=DeviceAuthorizationState.APPROVED)
        key_store = InMemoryDeviceKeyStore()
        ui = RecordingEnrollmentUi()
        acl = RecordingAclEnforcer()
        config_path = tmp_path / "agent" / "agent.toml"
        workspace_root = tmp_path / "workspace"
        workspace_root.mkdir()
        codex_binary = str(tmp_path / "codex-0.145.0.exe")
        monkeypatch.setattr(setup_module.asyncio, "sleep", self._ignore_sleep)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://control.example",
        ) as client:
            settings = await CodexAgentSetupUsecase(
                client=client,
                key_store=key_store,
                ui=ui,
                acl_enforcer=acl,
            ).execute(
                config_path=config_path,
                api_url="https://control.example/",
                websocket_url="wss://control.example/internal/codex-agents/connect",
                verification_url="http://127.0.0.1:3000/codex/verify-device",
                display_name="Workstation",
                platform="windows",
                expected_codex_version="0.145.0",
                codex_binary=codex_binary,
                agent_version=TEST_AGENT_VERSION,
                schema_digest=FROZEN_SCHEMA_DIGEST,
                workspace=AgentWorkspaceSettings(
                    key="work",
                    display_name="Work",
                    root=workspace_root,
                    allow_write=True,
                ),
            )

        assert settings.agent.host_id is not None
        assert settings.agent.key_id == transport.key_id
        assert settings.agent.key_id is not None
        assert settings.agent.codex_binary == codex_binary
        assert config_path.exists()
        assert acl.paths == [config_path]
        assert ui.user_code == USER_CODE
        assert ui.verification_uri == (
            f"http://127.0.0.1:3000/codex/verify-device?user_code={USER_CODE}"
        )
        assert (
            ui.fingerprint
            == hashlib.sha256(key_store.read_public_key(settings.agent.key_id)).hexdigest()
        )
        assert key_store.deleted == []
        assert transport.poll_count == 2
        persisted_settings = tomllib.loads(config_path.read_text(encoding="utf-8"))
        assert "legacy_credential_id" not in persisted_settings["agent"]
        assert persisted_settings["agent"]["codex_binary"] == codex_binary

    @pytest.mark.asyncio
    async def test_setup_when_denied_should_delete_generated_key(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import src.infrastructure.codex_agent.agent_setup as setup_module

        transport = DeviceAuthorizationTransport(terminal_state=DeviceAuthorizationState.DENIED)
        key_store = InMemoryDeviceKeyStore()
        monkeypatch.setattr(setup_module.asyncio, "sleep", self._ignore_sleep)
        workspace_root = tmp_path / "workspace"
        workspace_root.mkdir()
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://control.example",
        ) as client:
            with pytest.raises(PermissionError, match="未获批准"):
                await CodexAgentSetupUsecase(
                    client=client,
                    key_store=key_store,
                    ui=RecordingEnrollmentUi(),
                    acl_enforcer=RecordingAclEnforcer(),
                ).execute(
                    config_path=tmp_path / "agent.toml",
                    api_url="https://control.example",
                    websocket_url="wss://control.example/connect",
                    display_name="Denied",
                    platform="windows",
                    expected_codex_version="0.145.0",
                    agent_version=TEST_AGENT_VERSION,
                    schema_digest=FROZEN_SCHEMA_DIGEST,
                    workspace=AgentWorkspaceSettings(
                        key="work",
                        display_name="Work",
                        root=workspace_root,
                    ),
                )

        assert key_store.deleted == [transport.key_id]

    @pytest.mark.asyncio
    async def test_doctor_should_report_healthy_warn_blocked_and_network_failures(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import src.infrastructure.codex_agent.agent_doctor as doctor_module

        settings = self._settings(tmp_path)
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="codex-cli 0.145.0\n",
            stderr="",
        )
        monkeypatch.setattr(
            doctor_module.CodexProcessSupport,
            "resolve_command",
            lambda value: (value,),
        )
        monkeypatch.setattr(doctor_module.subprocess, "run", lambda *args, **kwargs: completed)
        monkeypatch.setattr(doctor_module.socket, "getaddrinfo", lambda *args: [(2, 1, 6)])

        healthy = await AgentDoctor(
            settings=settings,
            device_key_store=ReadableDeviceKeyStore(),
        ).run()

        assert healthy.exit_code is AgentDoctorExitCode.HEALTHY
        assert healthy.codex_version == "0.145.0"
        assert {check.state for check in healthy.checks} == {AgentDoctorCheckState.PASS}

        class MissingLegacySecretStore:
            def read(self, credential_id: str) -> str:
                raise AgentSecretNotFoundError(f"旧凭据不存在：{credential_id}")

            def write(self, credential_id: str, token: str) -> None:
                raise AssertionError(f"doctor 不应写入旧凭据：{credential_id}:{len(token)}")

            def delete(self, credential_id: str) -> None:
                raise AssertionError(f"doctor 不应删除旧凭据：{credential_id}")

        healthy_with_legacy_store = await AgentDoctor(
            settings=settings,
            secret_store=MissingLegacySecretStore(),
            device_key_store=ReadableDeviceKeyStore(),
        ).run()
        assert healthy_with_legacy_store.exit_code is AgentDoctorExitCode.HEALTHY

        missing_workspace = tmp_path / "missing"
        warn_settings = settings.model_copy(
            update={
                "agent": settings.agent.model_copy(update={"key_id": None}),
                "workspaces": [
                    settings.workspaces[0].model_copy(update={"root": missing_workspace})
                ],
            }
        )
        warned = await AgentDoctor(settings=warn_settings).run()
        assert warned.exit_code is AgentDoctorExitCode.USER_ACTION_REQUIRED

        monkeypatch.setattr(
            doctor_module.subprocess,
            "run",
            lambda *args, **kwargs: (_ for _ in ()).throw(subprocess.SubprocessError()),
        )
        blocked = await AgentDoctor(
            settings=settings,
            device_key_store=ReadableDeviceKeyStore(fail=True),
        ).run()
        assert blocked.exit_code is AgentDoctorExitCode.COMPATIBILITY_BLOCKED
        assert blocked.codex_version is None

        monkeypatch.setattr(
            doctor_module.socket,
            "getaddrinfo",
            lambda *args: (_ for _ in ()).throw(OSError()),
        )
        failed = await AgentDoctor(
            settings=settings,
            device_key_store=ReadableDeviceKeyStore(),
        ).run()
        assert failed.exit_code is AgentDoctorExitCode.NETWORK_FAILURE

        invalid_url_settings = settings.model_copy(
            update={"agent": settings.agent.model_copy(update={"control_plane_url": "ws://"})}
        )
        invalid_url = await AgentDoctor(
            settings=invalid_url_settings,
            device_key_store=ReadableDeviceKeyStore(),
        ).run()
        assert invalid_url.exit_code is AgentDoctorExitCode.NETWORK_FAILURE

    def test_doctor_state_database_and_exit_priority_should_fail_closed(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import src.infrastructure.codex_agent.agent_doctor as doctor_module

        doctor = AgentDoctor(settings=self._settings(tmp_path))
        monkeypatch.setattr(
            doctor_module.sqlite3,
            "connect",
            lambda path: (_ for _ in ()).throw(sqlite3.Error(str(path))),
        )
        check = doctor._check_state_database()  # noqa: SLF001
        assert check.state is AgentDoctorCheckState.FAILED

        checks = (
            AgentDoctorCheck(name="warn", state=AgentDoctorCheckState.WARN, reason_code="warn"),
            AgentDoctorCheck(
                name="blocked",
                state=AgentDoctorCheckState.BLOCKED,
                reason_code="blocked",
            ),
            AgentDoctorCheck(
                name="failed",
                state=AgentDoctorCheckState.FAILED,
                reason_code="failed",
            ),
        )
        assert doctor._choose_exit_code(checks) is AgentDoctorExitCode.NETWORK_FAILURE  # noqa: SLF001
        assert (  # noqa: SLF001
            doctor._choose_exit_code(checks[:2]) is AgentDoctorExitCode.COMPATIBILITY_BLOCKED
        )
        assert (  # noqa: SLF001
            doctor._choose_exit_code(checks[:1]) is AgentDoctorExitCode.USER_ACTION_REQUIRED
        )

    def test_dpapi_key_store_should_generate_sign_read_delete_and_reject_invalid_key(
        self,
        tmp_path: Path,
    ) -> None:
        key_id = uuid4()
        acl = RecordingAclEnforcer()
        store = WindowsDpapiDeviceKeyStore(
            root=tmp_path / "keys",
            dpapi=PassthroughDpapi(),
            acl_enforcer=acl,
        )

        public_key = store.generate(key_id)
        signature = store.sign(key_id, b"message")
        Ed25519PrivateKey.from_private_bytes(
            PassthroughDpapi().unprotect((tmp_path / "keys" / f"{key_id}.dpapi").read_bytes())
        ).public_key().verify(signature, b"message")

        assert len(public_key) == PRIVATE_KEY_LENGTH
        assert store.read_public_key(key_id) == public_key
        assert acl.paths == [tmp_path / "keys" / f"{key_id}.dpapi"]
        store.delete(key_id)
        assert not (tmp_path / "keys" / f"{key_id}.dpapi").exists()
        store.delete(key_id)

        invalid_id = uuid4()
        invalid_store = WindowsDpapiDeviceKeyStore(
            root=tmp_path / "invalid",
            dpapi=PassthroughDpapi(invalid_length=True),
            acl_enforcer=acl,
        )
        (tmp_path / "invalid").mkdir()
        (tmp_path / "invalid" / f"{invalid_id}.dpapi").write_bytes(b"protected:invalid")
        with pytest.raises(ValueError, match="长度"):
            invalid_store.read_public_key(invalid_id)

    def test_native_dpapi_and_acl_should_reject_non_windows_session(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import src.infrastructure.codex_agent.agent_setup as setup_module
        import src.infrastructure.codex_agent.windows_dpapi_device_key_store as dpapi_module

        monkeypatch.setattr(dpapi_module.sys, "platform", "linux")
        monkeypatch.setattr(setup_module.sys, "platform", "linux")
        with pytest.raises(OSError, match="Windows"):
            WindowsCurrentUserDpapi().protect(b"secret")
        with pytest.raises(OSError, match="Windows"):
            WindowsCurrentUserDpapi().unprotect(b"secret")
        with pytest.raises(OSError, match="Windows"):
            WindowsCurrentUserAclEnforcer().enforce(Path("key.dpapi"))
        with pytest.raises(OSError, match="Windows"):
            WindowsEnrollmentUi().show(
                verification_uri="https://control.example/device",
                user_code=USER_CODE,
                fingerprint="a" * 64,
            )

    def test_windows_acl_should_authorize_current_sid_with_icacls_sid_prefix(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import src.infrastructure.codex_agent.windows_dpapi_device_key_store as dpapi_module

        acl_path = tmp_path / "device.dpapi"
        acl_path.write_bytes(b"protected")
        calls: list[list[str]] = []
        current_sid = "S-1-5-21-100-200-300-1001"

        def run_command(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append(command)
            if command[0] == dpapi_module.CURRENT_USER_COMMAND:
                return subprocess.CompletedProcess(
                    args=command,
                    returncode=0,
                    stdout=f'"User","{current_sid}"\n',
                    stderr="",
                )
            return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")

        monkeypatch.setattr(dpapi_module.sys, "platform", "win32")
        monkeypatch.setattr(dpapi_module.subprocess, "run", run_command)
        try:
            WindowsCurrentUserAclEnforcer().enforce(acl_path)
            assert calls[1] == [
                dpapi_module.POWERSHELL_ACL_EXECUTABLE,
                str(acl_path),
                "/inheritance:r",
                "/grant:r",
                f"*{current_sid}:(R,W)",
            ]
        finally:
            acl_path.unlink(missing_ok=True)

    def test_setup_create_request_should_bind_public_key_and_signature(
        self, tmp_path: Path
    ) -> None:
        key_store = InMemoryDeviceKeyStore()
        key_id = uuid4()
        public_key = key_store.generate(key_id)
        usecase = CodexAgentSetupUsecase(
            client=httpx.AsyncClient(),
            key_store=key_store,
            ui=RecordingEnrollmentUi(),
            acl_enforcer=RecordingAclEnforcer(),
        )
        try:
            request = usecase._build_create_request(  # noqa: SLF001
                key_id=key_id,
                public_key=public_key,
                display_name="Workstation",
                platform="windows",
            )
        finally:
            import asyncio

            asyncio.run(usecase._client.aclose())  # noqa: SLF001

        assert base64.b64decode(request.detail.public_key_base64) == public_key
        assert len(base64.b64decode(request.detail.nonce_signature_base64)) == 64
        assert len(request.detail.nonce) >= 32

    def _settings(self, tmp_path: Path) -> CodexHostAgentSettings:
        workspace_root = tmp_path / "workspace"
        workspace_root.mkdir(exist_ok=True)
        return CodexHostAgentSettings(
            agent=AgentProcessSettings(
                host_id=uuid4(),
                key_id=uuid4(),
                display_name="Doctor",
                control_plane_url="wss://localhost:443/internal/codex-agents/connect",
                control_plane_api_url="https://localhost",
                codex_binary="codex",
                state_database=tmp_path / "state.sqlite",
            ),
            protocol=AgentProtocolSettings(
                agent_schema_version=CodexConnectionProtocolVersion.V2,
                expected_codex_version="0.145.0",
                app_server_schema_digest=FROZEN_SCHEMA_DIGEST,
            ),
            workspaces=[
                AgentWorkspaceSettings(
                    key="work",
                    display_name="Work",
                    root=workspace_root,
                    allow_write=True,
                )
            ],
        )

    @staticmethod
    async def _ignore_sleep(_seconds: float) -> None:
        return None
