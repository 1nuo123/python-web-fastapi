"""Windows Agent bootstrap、安装身份与本地幂等边界单元测试。"""

from __future__ import annotations

import hashlib
import logging
import subprocess
import tomllib
from pathlib import Path
from typing import Literal

import httpx
import pytest
from pydantic import ValidationError

from src.cli.build_codex_agent_bootstrap import (
    AgentBootstrapBuildCommand,
    CodexAgentBootstrapBuilder,
)
from src.cli.build_codex_agent_installer_identity import (
    CodexAgentWindowsInstallerIdentityBuilder,
    WindowsInstallerIdentityBuildCommand,
)
from src.cli.build_codex_agent_windows_version_info import (
    CodexAgentWindowsVersionInfoBuilder,
    WindowsVersionInfoBuildCommand,
)
from src.cli.run_codex_host_agent import CodexHostAgentCli
from src.core.artifact_release_contract.artifact_contract import (
    ArtifactArchitecture,
    ArtifactChannel,
    ArtifactPlatform,
)
from src.infrastructure.artifact_release.signed_activation import (
    ActiveArtifactVersionRecord,
)
from src.infrastructure.codex_agent.agent_configuration import (
    AgentBootstrapConnectionSettings,
    AgentBootstrapSettings,
    AgentLocalBootstrapConnectionSettings,
    AgentReleaseBootstrapSettings,
)
from src.infrastructure.codex_agent.agent_executable_selector import (
    AgentExecutableSelector,
    WindowsAgentFileVersionReader,
)
from src.infrastructure.codex_agent.agent_runtime_version import AgentRuntimeVersionResolver
from src.infrastructure.codex_agent.windows_agent_task import (
    WindowsAgentTaskIdentityResolver,
)
from src.infrastructure.process.windows_subprocess_launcher import (
    WindowsSubprocessLauncher,
    WindowsSubprocessRequest,
    WindowsSubprocessResult,
)

SCHEMA_DIGEST = "a" * 64
SIGNER_SHA256 = "c" * 64
ENROLLMENT_URI = "codexremote://enroll?token=" + "t" * 48
CURRENT_USER_SID = "S-1-5-21-100-200-300-1001"
TEST_LAUNCH_RETURN_CODE = 17


class StubAgentFileVersionReader:
    """按测试路径返回 Windows 文件版本。"""

    def __init__(self, versions: dict[Path, str]) -> None:
        self._versions = {path.resolve(): version for path, version in versions.items()}

    def read(self, path: Path) -> str:
        return self._versions[path.resolve()]


class RecordingAgentSignatureVerifier:
    """记录活动 Agent 签名校验。"""

    def __init__(self, *, rejected_paths: set[Path] | None = None) -> None:
        self.rejected_paths = {path.resolve() for path in (rejected_paths or set())}
        self.paths: list[Path] = []

    async def verify(self, path: Path) -> object:
        resolved = path.resolve()
        self.paths.append(resolved)
        if resolved in self.rejected_paths:
            raise ValueError("invalid signature")
        return object()


class RecordingLifecycleSubprocessLauncher(WindowsSubprocessLauncher):
    """记录稳定入口对外部 Agent 生命周期的转发。"""

    def __init__(self) -> None:
        self.requests: list[WindowsSubprocessRequest] = []

    def run(self, request: WindowsSubprocessRequest) -> WindowsSubprocessResult:
        self.requests.append(request)
        return WindowsSubprocessResult(
            return_code=TEST_LAUNCH_RETURN_CODE,
            stdout="",
            stderr="",
            elapsed_seconds=0,
            log_id="agent-lifecycle-test",
        )


class TestAgentStableLauncherUnit:
    """覆盖稳定入口的同进程运行和外部版本生命周期等待。"""

    def test_installed_agent_should_run_in_current_process(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import src.cli.run_codex_host_agent as cli_module

        forwarded_arguments: list[str] = []
        cli = CodexHostAgentCli()

        async def select_installed(
            _self: AgentExecutableSelector,
            **_kwargs: object,
        ) -> Path:
            return Path(cli_module.sys.executable)

        def execute_forwarded(arguments: list[str]) -> int:
            forwarded_arguments.extend(arguments)
            return TEST_LAUNCH_RETURN_CODE

        monkeypatch.setattr(
            cli_module.AgentBootstrapSettingsLoader,
            "load",
            lambda _self, _path: _configured_bootstrap(),
        )
        monkeypatch.setattr(cli_module.AgentExecutableSelector, "select", select_installed)
        monkeypatch.setattr(cli, "execute", execute_forwarded)

        result = cli.run_launcher(
            config_path=tmp_path / "agent.toml",
            bootstrap_path=tmp_path / "agent-bootstrap.toml",
            launch_command="run",
            uri=None,
        )

        assert result == TEST_LAUNCH_RETURN_CODE
        assert forwarded_arguments == [
            "--config",
            str(tmp_path / "agent.toml"),
            "--bootstrap",
            str(tmp_path / "agent-bootstrap.toml"),
            "run",
        ]

    def test_active_agent_should_wait_without_lifecycle_timeout(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import src.cli.run_codex_host_agent as cli_module

        active_executable = tmp_path / "releases" / "codex-remote-agent.exe"
        active_executable.parent.mkdir()
        active_executable.touch()
        launcher = RecordingLifecycleSubprocessLauncher()
        cli = CodexHostAgentCli(subprocess_launcher=launcher)

        async def select_active(
            _self: AgentExecutableSelector,
            **_kwargs: object,
        ) -> Path:
            return active_executable

        monkeypatch.setattr(
            cli_module.AgentBootstrapSettingsLoader,
            "load",
            lambda _self, _path: _configured_bootstrap(),
        )
        monkeypatch.setattr(cli_module.AgentExecutableSelector, "select", select_active)

        result = cli.run_launcher(
            config_path=tmp_path / "agent.toml",
            bootstrap_path=tmp_path / "agent-bootstrap.toml",
            launch_command="settings",
            uri=None,
        )

        assert result == TEST_LAUNCH_RETURN_CODE
        assert len(launcher.requests) == 1
        request = launcher.requests[0]
        assert request.timeout_seconds is None
        assert request.argv == (
            str(active_executable),
            "--config",
            str(tmp_path / "agent.toml"),
            "--bootstrap",
            str(tmp_path / "agent-bootstrap.toml"),
            "settings",
        )


def test_windows_file_version_reader_on_non_windows_should_reject(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    executable = tmp_path / "codex-remote-agent.exe"
    executable.write_bytes(b"not-a-windows-executable")
    monkeypatch.setattr(
        "src.infrastructure.codex_agent.agent_executable_selector.sys.platform",
        "linux",
    )

    with pytest.raises(OSError, match="Windows"):
        WindowsAgentFileVersionReader().read(executable)


def _configured_bootstrap() -> AgentBootstrapSettings:
    return AgentBootstrapSettings(
        deployment_state="configured",
        connection=AgentBootstrapConnectionSettings(
            api_url="https://agent.acme.dev",
            websocket_url="wss://agent.acme.dev/internal/codex-agents/connect",
            verification_url="https://agent.acme.dev/codex/verify-device",
            website_url="https://agent.acme.dev",
        ),
        agent_version="0.1.1",
        expected_codex_version="0.145.0",
        app_server_schema_digest=SCHEMA_DIGEST,
    )


def _unconfigured_bootstrap() -> AgentBootstrapSettings:
    return AgentBootstrapSettings(
        deployment_state="unconfigured",
        agent_version="0.1.1",
        expected_codex_version="0.145.0",
        app_server_schema_digest=SCHEMA_DIGEST,
    )


def _local_bootstrap() -> AgentBootstrapSettings:
    return AgentBootstrapSettings(
        deployment_state="local",
        connection=AgentLocalBootstrapConnectionSettings.from_local_origin("http://localhost:8080"),
        agent_version="0.1.1",
        expected_codex_version="0.145.0",
        app_server_schema_digest=SCHEMA_DIGEST,
    )


def _release_bootstrap(version: str) -> AgentBootstrapSettings:
    return AgentBootstrapSettings(
        deployment_state="configured",
        connection=AgentBootstrapConnectionSettings.from_public_origin("https://agent.acme.dev"),
        agent_version=version,
        expected_codex_version="0.145.0",
        app_server_schema_digest=SCHEMA_DIGEST,
        release=AgentReleaseBootstrapSettings(
            repository_url="https://updates.acme.dev",
            repository_host_allowlist=("updates.acme.dev",),
            authenticode_signer_sha256_allowlist=(SIGNER_SHA256,),
            trusted_root_file_name="root.json",
            max_download_bytes=536_870_912,
            request_timeout_seconds=60,
            retained_versions=2,
            health_timeout_seconds=60,
            rollback_budget=3,
            minimum_security_version=version,
        ),
    )


def _write_active_release(
    releases_root: Path,
    *,
    version: str,
    content: bytes,
) -> Path:
    executable = (
        releases_root
        / "codex-remote-agent.exe"
        / ArtifactPlatform.WINDOWS.value
        / ArtifactArchitecture.X86_64.value
        / ArtifactChannel.STABLE.value
        / version
        / "codex-remote-agent.exe"
    )
    executable.parent.mkdir(parents=True)
    executable.write_bytes(content)
    (releases_root / "active-version.json").write_text(
        ActiveArtifactVersionRecord(
            artifact_name="codex-remote-agent.exe",
            platform=ArtifactPlatform.WINDOWS,
            architecture=ArtifactArchitecture.X86_64,
            channel=ArtifactChannel.STABLE,
            version=version,
            digest_sha256=hashlib.sha256(content).hexdigest(),
            path=executable,
        ).model_dump_json(),
        "utf-8",
    )
    return executable


def test_bootstrap_builder_when_unconfigured_should_not_emit_any_url(tmp_path: Path) -> None:
    output = tmp_path / "agent-bootstrap.toml"

    CodexAgentBootstrapBuilder().build(
        AgentBootstrapBuildCommand(
            output=output,
            deployment_state="unconfigured",
            agent_version="0.1.1",
            expected_codex_version="0.145.0",
            app_server_schema_digest=SCHEMA_DIGEST,
        )
    )

    content = output.read_text("utf-8")
    payload = tomllib.loads(content)
    assert payload["deployment_state"] == "unconfigured"
    assert "connection" not in payload
    assert "release" not in payload
    assert "://" not in content


def test_bootstrap_builder_should_derive_all_endpoints_from_public_origin(tmp_path: Path) -> None:
    output = tmp_path / "agent-bootstrap.toml"

    CodexAgentBootstrapBuilder().build(
        AgentBootstrapBuildCommand(
            output=output,
            public_origin="https://agent.acme.dev:8443/",
            agent_version="0.1.1",
            expected_codex_version="0.145.0",
            app_server_schema_digest=SCHEMA_DIGEST,
        )
    )

    connection = tomllib.loads(output.read_text("utf-8"))["connection"]
    assert connection == {
        "api_url": "https://agent.acme.dev:8443",
        "websocket_url": "wss://agent.acme.dev:8443/internal/codex-agents/connect",
        "verification_url": "https://agent.acme.dev:8443/codex/verify-device",
        "website_url": "https://agent.acme.dev:8443",
    }


@pytest.mark.parametrize(
    "local_origin,expected_authority",
    [
        ("http://localhost:8080/", "localhost:8080"),
        ("http://127.0.0.1:8080", "127.0.0.1:8080"),
        ("http://[::1]:8080", "[::1]:8080"),
    ],
)
def test_bootstrap_builder_should_derive_loopback_endpoints_for_local_acceptance(
    tmp_path: Path,
    local_origin: str,
    expected_authority: str,
) -> None:
    output = tmp_path / "agent-bootstrap.toml"

    CodexAgentBootstrapBuilder().build(
        AgentBootstrapBuildCommand(
            output=output,
            deployment_state="local",
            local_origin=local_origin,
            agent_version="0.1.1",
            expected_codex_version="0.145.0",
            app_server_schema_digest=SCHEMA_DIGEST,
        )
    )

    payload = tomllib.loads(output.read_text("utf-8"))
    assert payload["deployment_state"] == "local"
    assert payload["connection"] == {
        "api_url": f"http://{expected_authority}",
        "websocket_url": (f"ws://{expected_authority}/internal/codex-agents/connect"),
        "verification_url": f"http://{expected_authority}/codex/verify-device",
        "website_url": f"http://{expected_authority}",
    }
    assert "release" not in payload
    bootstrap = AgentBootstrapSettings.model_validate(payload)
    assert isinstance(bootstrap.connection, AgentLocalBootstrapConnectionSettings)


@pytest.mark.parametrize(
    "field_name,value",
    [
        ("api_url", "http://agent.acme.dev"),
        ("api_url", "https://localhost"),
        ("api_url", "https://127.0.0.1"),
        ("api_url", "https://agent.example.com"),
        ("websocket_url", "ws://agent.acme.dev/connect"),
    ],
)
def test_bootstrap_connection_when_not_public_tls_should_reject(
    field_name: str,
    value: str,
) -> None:
    payload = {
        "api_url": "https://agent.acme.dev",
        "websocket_url": "wss://agent.acme.dev/internal/codex-agents/connect",
        "verification_url": "https://agent.acme.dev/codex/verify-device",
        "website_url": "https://agent.acme.dev",
        field_name: value,
    }

    with pytest.raises(ValidationError):
        AgentBootstrapConnectionSettings.model_validate(payload)


@pytest.mark.parametrize(
    "field_name,value,error_pattern",
    [
        ("api_url", "https://api.acme.dev", "同一公网origin"),
        (
            "websocket_url",
            "wss://agent.acme.dev/internal/codex-agents/other",
            "路径或查询参数",
        ),
        (
            "verification_url",
            "https://agent.acme.dev/codex/verify-device?source=installer",
            "路径或查询参数",
        ),
        ("website_url", "https://agent.acme.dev/product", "路径或查询参数"),
    ],
)
def test_bootstrap_connection_when_origin_or_path_mismatches_should_reject(
    field_name: str,
    value: str,
    error_pattern: str,
) -> None:
    payload = {
        "api_url": "https://agent.acme.dev",
        "websocket_url": "wss://agent.acme.dev/internal/codex-agents/connect",
        "verification_url": "https://agent.acme.dev/codex/verify-device",
        "website_url": "https://agent.acme.dev",
        field_name: value,
    }

    with pytest.raises(ValidationError, match=error_pattern):
        AgentBootstrapConnectionSettings.model_validate(payload)


@pytest.mark.parametrize(
    "field_name,value",
    [
        ("api_url", "https://localhost:8080"),
        ("api_url", "http://192.168.1.20:8080"),
        ("api_url", "http://127.0.0.2:8080"),
        ("api_url", "http://agent.acme.dev:8080"),
        ("websocket_url", "wss://localhost:8080/internal/codex-agents/connect"),
    ],
)
def test_local_bootstrap_connection_when_not_exact_loopback_should_reject(
    field_name: str,
    value: str,
) -> None:
    payload = _local_bootstrap().connection.model_dump(mode="json")
    payload[field_name] = value

    with pytest.raises(ValidationError):
        AgentLocalBootstrapConnectionSettings.model_validate(payload)


@pytest.mark.parametrize(
    "field_name,value,error_pattern",
    [
        ("api_url", "http://127.0.0.1:8080", "同一回环origin"),
        (
            "websocket_url",
            "ws://localhost:8080/internal/codex-agents/other",
            "路径或查询参数",
        ),
        (
            "verification_url",
            "http://localhost:8080/codex/verify-device?source=installer",
            "路径或查询参数",
        ),
        ("website_url", "http://localhost:8080/product", "路径或查询参数"),
    ],
)
def test_local_bootstrap_connection_when_origin_or_path_mismatches_should_reject(
    field_name: str,
    value: str,
    error_pattern: str,
) -> None:
    payload = _local_bootstrap().connection.model_dump(mode="json")
    payload[field_name] = value

    with pytest.raises(ValidationError, match=error_pattern):
        AgentLocalBootstrapConnectionSettings.model_validate(payload)


@pytest.mark.parametrize(
    "public_origin",
    [
        "https://agent.acme.dev/control",
        "https://agent.acme.dev?tenant=one",
    ],
)
def test_bootstrap_builder_when_public_origin_is_not_origin_should_reject(
    tmp_path: Path,
    public_origin: str,
) -> None:
    with pytest.raises(ValidationError, match="公网origin"):
        AgentBootstrapBuildCommand(
            output=tmp_path / "agent-bootstrap.toml",
            public_origin=public_origin,
            agent_version="0.1.1",
            expected_codex_version="0.145.0",
            app_server_schema_digest=SCHEMA_DIGEST,
        )


def test_bootstrap_when_unconfigured_contains_connection_should_reject() -> None:
    with pytest.raises(ValidationError, match="未配置"):
        AgentBootstrapSettings(
            deployment_state="unconfigured",
            connection=_configured_bootstrap().connection,
            agent_version="0.1.1",
            expected_codex_version="0.145.0",
            app_server_schema_digest=SCHEMA_DIGEST,
        )


def test_bootstrap_when_local_contains_public_connection_should_reject() -> None:
    with pytest.raises(ValidationError, match="回环控制面"):
        AgentBootstrapSettings(
            deployment_state="local",
            connection=_configured_bootstrap().connection,
            agent_version="0.1.1",
            expected_codex_version="0.145.0",
            app_server_schema_digest=SCHEMA_DIGEST,
        )


def test_bootstrap_when_configured_contains_local_connection_should_reject() -> None:
    with pytest.raises(ValidationError, match="正式控制面"):
        AgentBootstrapSettings(
            deployment_state="configured",
            connection=_local_bootstrap().connection,
            agent_version="0.1.1",
            expected_codex_version="0.145.0",
            app_server_schema_digest=SCHEMA_DIGEST,
        )


def test_bootstrap_builder_when_local_release_enabled_should_reject(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="本地验收.*自动更新"):
        AgentBootstrapBuildCommand(
            output=tmp_path / "agent-bootstrap.toml",
            deployment_state="local",
            local_origin="http://localhost:8080",
            agent_version="0.1.1",
            expected_codex_version="0.145.0",
            app_server_schema_digest=SCHEMA_DIGEST,
            release_enabled=True,
        )


@pytest.mark.parametrize(
    "deployment_state,public_origin,local_origin,error_pattern",
    [
        ("local", "https://agent.acme.dev", "http://localhost:8080", "公网origin"),
        ("configured", "https://agent.acme.dev", "http://localhost:8080", "本地origin"),
        ("unconfigured", None, "http://localhost:8080", "服务器地址"),
    ],
)
def test_bootstrap_builder_when_origin_does_not_match_deployment_should_reject(
    tmp_path: Path,
    deployment_state: Literal["configured", "local", "unconfigured"],
    public_origin: str | None,
    local_origin: str | None,
    error_pattern: str,
) -> None:
    with pytest.raises(ValidationError, match=error_pattern):
        AgentBootstrapBuildCommand(
            output=tmp_path / "agent-bootstrap.toml",
            deployment_state=deployment_state,
            public_origin=public_origin,
            local_origin=local_origin,
            agent_version="0.1.1",
            expected_codex_version="0.145.0",
            app_server_schema_digest=SCHEMA_DIGEST,
        )


def test_bootstrap_builder_when_release_host_not_allowlisted_should_reject(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValidationError, match="allowlist"):
        AgentBootstrapBuildCommand(
            output=tmp_path / "agent-bootstrap.toml",
            public_origin="https://agent.acme.dev",
            agent_version="0.1.1",
            expected_codex_version="0.145.0",
            app_server_schema_digest=SCHEMA_DIGEST,
            release_enabled=True,
            release_manifest_target_path="codex-agent-release.json",
            release_repository_url="https://updates.acme.dev",
            repository_host_allowlist=("other.acme.dev",),
            authenticode_signer_sha256_allowlist=(SIGNER_SHA256,),
            minimum_security_version="0.1.1",
        )


def test_bootstrap_builder_when_manifest_target_is_not_protocol_constant_should_reject(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValidationError, match="codex-agent-release.json"):
        AgentBootstrapBuildCommand(
            output=tmp_path / "agent-bootstrap.toml",
            public_origin="https://agent.acme.dev",
            agent_version="0.1.1",
            expected_codex_version="0.145.0",
            app_server_schema_digest=SCHEMA_DIGEST,
            release_enabled=True,
            release_manifest_target_path="other-release.json",  # type: ignore[arg-type]
            release_repository_url="https://updates.acme.dev",
            repository_host_allowlist=("updates.acme.dev",),
            authenticode_signer_sha256_allowlist=(SIGNER_SHA256,),
            minimum_security_version="0.1.1",
        )


def test_bootstrap_builder_when_security_floor_above_agent_should_reject(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValidationError, match="最低安全版本"):
        AgentBootstrapBuildCommand(
            output=tmp_path / "agent-bootstrap.toml",
            public_origin="https://agent.acme.dev",
            agent_version="0.1.1",
            expected_codex_version="0.145.0",
            app_server_schema_digest=SCHEMA_DIGEST,
            release_enabled=True,
            release_manifest_target_path="codex-agent-release.json",
            release_repository_url="https://updates.acme.dev",
            repository_host_allowlist=("updates.acme.dev",),
            authenticode_signer_sha256_allowlist=(SIGNER_SHA256,),
            minimum_security_version="0.1.2",
        )


def test_installer_identity_when_same_version_should_be_deterministic(tmp_path: Path) -> None:
    builder = CodexAgentWindowsInstallerIdentityBuilder()

    first = builder.build(
        WindowsInstallerIdentityBuildCommand(
            version="0.1.1",
            output=tmp_path / "first.json",
        )
    )
    second = builder.build(
        WindowsInstallerIdentityBuildCommand(
            version="0.1.1",
            output=tmp_path / "second.json",
        )
    )
    upgrade = builder.build(
        WindowsInstallerIdentityBuildCommand(
            version="0.1.2",
            output=tmp_path / "upgrade.json",
        )
    )

    assert first.product_code == second.product_code
    assert first.product_code != upgrade.product_code
    assert first.upgrade_code == upgrade.upgrade_code


def test_windows_version_info_should_match_release_version(tmp_path: Path) -> None:
    output = tmp_path / "version-info.txt"

    CodexAgentWindowsVersionInfoBuilder().build(
        WindowsVersionInfoBuildCommand(version="0.1.2", output=output)
    )

    content = output.read_text("utf-8")
    assert "filevers=(0, 1, 2, 0)" in content
    assert "prodvers=(0, 1, 2, 0)" in content
    assert "ProductVersion', '0.1.2.0'" in content


def test_task_name_when_current_user_should_include_stable_sid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completed = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout=f'"desktop\\user","{CURRENT_USER_SID}"\n',
        stderr="",
    )
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: completed)

    assert (
        WindowsAgentTaskIdentityResolver().resolve_current_user_task_name()
        == f"CodexRemoteAgent-{CURRENT_USER_SID}"
    )


def test_run_uri_when_agent_config_exists_should_not_enroll_again(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.cli.run_codex_host_agent as cli_module

    config_path = tmp_path / "agent.toml"
    config_path.touch()
    cli = CodexHostAgentCli()
    starts: list[bool] = []
    messages: list[str] = []
    monkeypatch.setattr(
        cli_module.AgentBootstrapSettingsLoader,
        "load",
        lambda _self, _path: _unconfigured_bootstrap(),
    )
    monkeypatch.setattr(cli, "load_settings", lambda _path: object())
    monkeypatch.setattr(
        cli,
        "_start_scheduled_agent",
        lambda started_config_path: starts.append(started_config_path == config_path),
    )
    monkeypatch.setattr(
        cli_module.WindowsEnrollmentUi,
        "show_info",
        lambda _self, message: messages.append(message),
    )
    monkeypatch.setattr(
        cli,
        "run_setup",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("不得重复注册")),
    )

    result = cli.run_uri(
        config_path=config_path,
        bootstrap_path=tmp_path / "bootstrap.toml",
        uri=ENROLLMENT_URI,
    )

    assert result == 0
    assert starts == [True]
    assert messages == ["这台电脑已经连接。Agent 已启动，不会重复注册设备。"]


def test_run_uri_when_package_unconfigured_should_fail_before_enrollment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.cli.run_codex_host_agent as cli_module

    cli = CodexHostAgentCli()
    monkeypatch.setattr(
        cli_module.AgentBootstrapSettingsLoader,
        "load",
        lambda _self, _path: _unconfigured_bootstrap(),
    )
    monkeypatch.setattr(
        cli,
        "run_setup",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("不得发起网络注册")),
    )

    with pytest.raises(ValueError, match="尚未配置正式服务器"):
        cli.run_uri(
            config_path=tmp_path / "agent.toml",
            bootstrap_path=tmp_path / "bootstrap.toml",
            uri=ENROLLMENT_URI,
        )


def test_interactive_error_when_http_failure_should_not_expose_request_url() -> None:
    request = httpx.Request(
        "POST",
        "https://agent.acme.dev/connect?token=secret-enrollment-token",
    )
    response = httpx.Response(403, request=request)
    error = httpx.HTTPStatusError("forbidden", request=request, response=response)

    message = CodexHostAgentCli()._format_interactive_error(error)  # noqa: SLF001

    assert message == "服务器拒绝了连接请求，请返回网站重新发起电脑连接。"
    assert "token" not in message
    assert "secret" not in message


def test_logging_when_configured_twice_should_keep_single_rotating_handler(
    tmp_path: Path,
) -> None:
    cli = CodexHostAgentCli()
    agent_logger = logging.getLogger("codex_host_agent")
    original_handlers = list(agent_logger.handlers)
    original_level = agent_logger.level
    original_propagate = agent_logger.propagate
    try:
        cli._configure_logging(tmp_path)  # noqa: SLF001
        cli._configure_logging(tmp_path)  # noqa: SLF001
        handlers = [
            handler
            for handler in agent_logger.handlers
            if isinstance(handler, logging.handlers.RotatingFileHandler)
            and Path(handler.baseFilename) == tmp_path / "logs" / "agent.log"
        ]
        assert len(handlers) == 1
        assert agent_logger.level == logging.INFO
        assert agent_logger.propagate is False
    finally:
        for handler in agent_logger.handlers:
            if handler not in original_handlers:
                handler.close()
                agent_logger.removeHandler(handler)
        agent_logger.setLevel(original_level)
        agent_logger.propagate = original_propagate


def test_runtime_version_when_active_executable_matches_should_use_release_version(
    tmp_path: Path,
) -> None:
    releases_root = tmp_path / "releases"
    executable = (
        releases_root
        / "codex-remote-agent.exe"
        / "windows"
        / "version"
        / ("codex-remote-agent.exe")
    )
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"release-0.1.2")
    (releases_root / "active-version.json").write_text(
        ActiveArtifactVersionRecord(
            artifact_name="codex-remote-agent.exe",
            platform=ArtifactPlatform.WINDOWS,
            architecture=ArtifactArchitecture.X86_64,
            channel=ArtifactChannel.STABLE,
            version="0.1.2",
            digest_sha256=hashlib.sha256(b"release-0.1.2").hexdigest(),
            path=executable,
        ).model_dump_json(),
        "utf-8",
    )

    version = AgentRuntimeVersionResolver(releases_root=releases_root).resolve(
        installed_version="0.1.1",
        executable_path=executable,
    )

    assert version == "0.1.2"


@pytest.mark.asyncio
async def test_executable_selector_when_msi_is_newer_should_ignore_old_active_release(
    tmp_path: Path,
) -> None:
    installed = tmp_path / "installed" / "codex-remote-agent.exe"
    installed.parent.mkdir()
    installed.write_bytes(b"installed-0.1.4")
    releases_root = tmp_path / "releases"
    active = _write_active_release(
        releases_root,
        version="0.1.3",
        content=b"active-0.1.3",
    )
    verifier = RecordingAgentSignatureVerifier()

    selected = await AgentExecutableSelector(
        version_reader=StubAgentFileVersionReader(
            {
                installed: "0.1.4",
                active: "0.1.3",
            }
        ),
        signature_verifier=verifier,
    ).select(
        installed_executable_path=installed,
        releases_root=releases_root,
        bootstrap=_release_bootstrap("0.1.4"),
    )

    assert selected == installed.resolve()
    assert verifier.paths == [installed.resolve()]


@pytest.mark.asyncio
async def test_executable_selector_when_msi_file_version_mismatches_bootstrap_should_reject(
    tmp_path: Path,
) -> None:
    installed = tmp_path / "installed" / "codex-remote-agent.exe"
    installed.parent.mkdir()
    installed.write_bytes(b"installed-0.1.4")

    with pytest.raises(PermissionError, match="MSI内置Agent版本"):
        await AgentExecutableSelector(
            version_reader=StubAgentFileVersionReader({installed: "0.1.3"}),
            signature_verifier=RecordingAgentSignatureVerifier(),
        ).select(
            installed_executable_path=installed,
            releases_root=tmp_path / "releases",
            bootstrap=_release_bootstrap("0.1.4"),
        )


@pytest.mark.asyncio
async def test_executable_selector_when_active_release_is_newer_should_verify_and_select_it(
    tmp_path: Path,
) -> None:
    installed = tmp_path / "installed" / "codex-remote-agent.exe"
    installed.parent.mkdir()
    installed.write_bytes(b"installed-0.1.4")
    releases_root = tmp_path / "releases"
    active = _write_active_release(
        releases_root,
        version="0.1.5",
        content=b"active-0.1.5",
    )
    verifier = RecordingAgentSignatureVerifier()

    selected = await AgentExecutableSelector(
        version_reader=StubAgentFileVersionReader(
            {
                installed: "0.1.4",
                active: "0.1.5",
            }
        ),
        signature_verifier=verifier,
    ).select(
        installed_executable_path=installed,
        releases_root=releases_root,
        bootstrap=_release_bootstrap("0.1.4"),
    )

    assert selected == active.resolve()
    assert verifier.paths == [installed.resolve(), active.resolve()]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["digest", "signature", "file_version"])
async def test_executable_selector_when_active_release_is_invalid_should_use_msi(
    tmp_path: Path,
    failure: str,
) -> None:
    installed = tmp_path / "installed" / "codex-remote-agent.exe"
    installed.parent.mkdir()
    installed.write_bytes(b"installed-0.1.4")
    releases_root = tmp_path / "releases"
    active = _write_active_release(
        releases_root,
        version="0.1.5",
        content=b"active-0.1.5",
    )
    if failure == "digest":
        active.write_bytes(b"tampered")
    verifier = RecordingAgentSignatureVerifier(
        rejected_paths={active} if failure == "signature" else None
    )
    active_file_version = "0.1.6" if failure == "file_version" else "0.1.5"

    selected = await AgentExecutableSelector(
        version_reader=StubAgentFileVersionReader(
            {
                installed: "0.1.4",
                active: active_file_version,
            }
        ),
        signature_verifier=verifier,
    ).select(
        installed_executable_path=installed,
        releases_root=releases_root,
        bootstrap=_release_bootstrap("0.1.4"),
    )

    assert selected == installed.resolve()


@pytest.mark.asyncio
async def test_executable_selector_when_installed_signature_is_invalid_should_reject(
    tmp_path: Path,
) -> None:
    installed = tmp_path / "installed" / "codex-remote-agent.exe"
    installed.parent.mkdir()
    installed.write_bytes(b"installed-0.1.4")

    with pytest.raises(ValueError, match="invalid signature"):
        await AgentExecutableSelector(
            version_reader=StubAgentFileVersionReader({installed: "0.1.4"}),
            signature_verifier=RecordingAgentSignatureVerifier(rejected_paths={installed}),
        ).select(
            installed_executable_path=installed,
            releases_root=tmp_path / "releases",
            bootstrap=_release_bootstrap("0.1.4"),
        )
