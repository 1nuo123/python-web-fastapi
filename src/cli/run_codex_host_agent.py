"""启动 Windows Codex Host Agent。"""

from __future__ import annotations

import argparse
import asyncio
import logging
import logging.handlers
import os
import platform

# 此处只引用 SubprocessError，进程启动由受限 launcher 负责。
import subprocess  # nosec B404
import sys
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Final
from urllib.parse import parse_qs, urlparse

import httpx
import portalocker
from loguru import logger

from src.core.artifact_release_contract.runtime_contract import (
    ArtifactReleaseRuntimeSettings,
)
from src.core.codex_contract.connection_session_contract import (
    CodexConnectionProtocolVersion,
)
from src.core.http_contract.outbound_http_client_contract import AsyncHttpClientDetail
from src.infrastructure.artifact_release.windows_authenticode_verifier import (
    WindowsAuthenticodeVerifier,
)
from src.infrastructure.codex_agent.agent_command_journal import AgentCommandJournal
from src.infrastructure.codex_agent.agent_configuration import (
    DEFAULT_AGENT_STATE_DIRECTORY,
    AgentBootstrapSettings,
    AgentBootstrapSettingsLoader,
    AgentWorkspaceSettings,
    CodexHostAgentSettings,
    CodexHostAgentSettingsLoader,
    build_agent_tls_context,
)
from src.infrastructure.codex_agent.agent_connection_ticket_provider import (
    AgentConnectionTicketProvider,
)
from src.infrastructure.codex_agent.agent_control_channel import AgentControlChannel
from src.infrastructure.codex_agent.agent_deployment_profile import (
    AgentDeploymentProfile,
    resolve_agent_deployment_paths,
)
from src.infrastructure.codex_agent.agent_doctor import AgentDoctor
from src.infrastructure.codex_agent.agent_executable_selector import (
    AgentExecutableSelector,
    WindowsAgentFileVersionReader,
)
from src.infrastructure.codex_agent.agent_release_runtime import CodexAgentReleaseRuntime
from src.infrastructure.codex_agent.agent_runtime_version import AgentRuntimeVersionResolver
from src.infrastructure.codex_agent.agent_secret_store import WindowsAgentSecretStore
from src.infrastructure.codex_agent.agent_settings_ui import WindowsAgentSettingsWindow
from src.infrastructure.codex_agent.agent_setup import (
    CodexAgentSetupUsecase,
    WindowsEnrollmentUi,
)
from src.infrastructure.codex_agent.agent_startup_updater import (
    AgentStartupUpdateState,
    AgentVersionPolicy,
    CodexAgentReleaseManifestClient,
    CodexAgentStartupUpdater,
    CodexAgentUpdateHealthCheck,
)
from src.infrastructure.codex_agent.agent_workspace_registry import (
    AgentWorkspaceRegistry,
    WindowsAgentConfigPermissionVerifier,
)
from src.infrastructure.codex_agent.app_server_process_supervisor import CodexProcessSupport
from src.infrastructure.codex_agent.windows_agent_task import (
    WindowsAgentTaskController,
)
from src.infrastructure.codex_agent.windows_dpapi_device_key_store import (
    WindowsCurrentUserAclEnforcer,
    WindowsDpapiDeviceKeyStore,
)
from src.infrastructure.process.windows_subprocess_launcher import (
    WindowsSubprocessLauncher,
    WindowsSubprocessLogCategory,
    WindowsSubprocessRequest,
)
from src.infrastructure.resource_slot.shared_async_http_client import SharedAsyncHttpClient

DEFAULT_AGENT_CONFIG_PATH: Final = DEFAULT_AGENT_STATE_DIRECTORY / "agent.toml"
AGENT_COMMAND_RUN: Final[str] = "run"
AGENT_COMMAND_DOCTOR: Final[str] = "doctor"
AGENT_COMMAND_SETUP: Final[str] = "setup"
AGENT_COMMAND_URI: Final[str] = "uri"
AGENT_COMMAND_SETTINGS: Final[str] = "settings"
AGENT_COMMAND_LAUNCH: Final[str] = "launch"
AGENT_BOOTSTRAP_FILE_NAME: Final[str] = "agent-bootstrap.toml"
AGENT_DEVELOPMENT_CA_CERTIFICATE_FILE_NAME: Final[str] = "codex-dev-root-ca.crt"
CODEX_REMOTE_URI_SCHEME: Final[str] = "codexremote"
CODEX_REMOTE_ENROLL_HOST: Final[str] = "enroll"
CODEX_REMOTE_TOKEN_QUERY_KEY: Final[str] = "token"
DEFAULT_AGENT_DISPLAY_NAME: Final[str] = "Windows 电脑"
DEFAULT_AGENT_VERSION: Final[str] = "0.1.0"
DEFAULT_CODEX_BINARY: Final[str] = "codex"
AGENT_UPDATE_RESTART_EXIT_CODE: Final[int] = 75
AGENT_HTTP_TIMEOUT_SECONDS = 30
AGENT_HTTP_MAX_CONNECTIONS = 8
AGENT_HTTP_MAX_KEEPALIVE_CONNECTIONS = 4
AGENT_LOG_MAX_BYTES = 5 * 1024 * 1024
AGENT_LOG_BACKUP_COUNT = 3
AGENT_USER_ERROR_EXIT_CODE = 2


class CodexHostAgentCli:
    """Agent 运行与诊断命令行入口。"""

    def __init__(self, subprocess_launcher: WindowsSubprocessLauncher | None = None) -> None:
        self._subprocess_launcher = subprocess_launcher or WindowsSubprocessLauncher()

    def build_argument_parser(self) -> argparse.ArgumentParser:
        """构建带子命令的参数解析器。"""

        parser = argparse.ArgumentParser(description="运行 Windows Codex 远程控制 Agent")
        parser.add_argument(
            "--deployment-profile",
            choices=[profile.value for profile in AgentDeploymentProfile],
            default=AgentDeploymentProfile.PRODUCTION.value,
        )
        parser.add_argument("--config", type=Path)
        parser.add_argument("--bootstrap", type=Path)
        subparsers = parser.add_subparsers(dest="command", required=False)
        subparsers.add_parser(AGENT_COMMAND_RUN, help="启动 Agent 主循环")
        subparsers.add_parser(AGENT_COMMAND_DOCTOR, help="执行脱敏诊断")
        setup_parser = subparsers.add_parser(AGENT_COMMAND_SETUP, help="首次绑定这台电脑")
        setup_parser.add_argument("--api-url", required=True)
        setup_parser.add_argument("--websocket-url", required=True)
        setup_parser.add_argument("--verification-url")
        setup_parser.add_argument("--display-name", required=True)
        setup_parser.add_argument("--workspace-root", type=Path, required=True)
        setup_parser.add_argument("--workspace-key", default="default")
        setup_parser.add_argument("--workspace-name", default="默认工作区")
        setup_parser.add_argument("--agent-version", default=DEFAULT_AGENT_VERSION)
        setup_parser.add_argument("--codex-version", required=True)
        setup_parser.add_argument("--codex-binary", default=DEFAULT_CODEX_BINARY)
        setup_parser.add_argument("--schema-digest", required=True)
        setup_parser.add_argument("--development-ca-certificate-path", type=Path)
        uri_parser = subparsers.add_parser(AGENT_COMMAND_URI, help="处理网站发起的设备连接")
        uri_parser.add_argument("uri")
        subparsers.add_parser(AGENT_COMMAND_SETTINGS, help="打开 Agent 设置窗口")
        launch_parser = subparsers.add_parser(AGENT_COMMAND_LAUNCH, help="选择可信版本并启动")
        launch_subparsers = launch_parser.add_subparsers(
            dest="launch_command",
            required=True,
        )
        launch_subparsers.add_parser(AGENT_COMMAND_RUN, help="启动 Agent 主循环")
        launch_uri_parser = launch_subparsers.add_parser(
            AGENT_COMMAND_URI,
            help="处理网站发起的设备连接",
        )
        launch_uri_parser.add_argument("uri")
        launch_subparsers.add_parser(AGENT_COMMAND_SETTINGS, help="打开 Agent 设置窗口")
        return parser

    def load_settings(self, config_path: Path) -> CodexHostAgentSettings:
        """按统一权限校验器加载强类型配置。"""

        return CodexHostAgentSettingsLoader(WindowsAgentConfigPermissionVerifier()).load(
            config_path
        )

    async def run_agent(
        self,
        settings: CodexHostAgentSettings,
        *,
        config_path: Path,
        bootstrap_path: Path,
        bootstrap: AgentBootstrapSettings,
    ) -> int:
        """加载本地资源并持有单实例锁运行 Agent。"""

        runtime_version = AgentRuntimeVersionResolver(
            releases_root=config_path.parent / "releases"
        ).resolve(
            installed_version=bootstrap.agent_version,
            executable_path=Path(sys.executable),
        )
        runtime_settings = settings.model_copy(
            update={
                "protocol": settings.protocol.model_copy(update={"agent_version": runtime_version})
            }
        )
        lock_path = runtime_settings.agent.state_database.with_suffix(".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        agent_logger = logging.getLogger("codex_host_agent")
        agent_logger.info(
            "启动 Codex Host Agent，工作区：%s",
            [workspace.display_name for workspace in runtime_settings.workspaces],
        )
        with portalocker.Lock(
            lock_path,
            mode="a",
            timeout=0,
            flags=portalocker.LockFlags.EXCLUSIVE | portalocker.LockFlags.NON_BLOCKING,
        ):
            with self._hold_runtime_profile_resources(
                state_directory=runtime_settings.agent.state_database.parent
            ):
                update_exit_code = await self._apply_startup_update(
                    settings=runtime_settings,
                    config_path=config_path,
                    bootstrap_path=bootstrap_path,
                    bootstrap=bootstrap,
                    agent_logger=agent_logger,
                )
                if update_exit_code is not None:
                    return update_exit_code
                journal = AgentCommandJournal(runtime_settings.agent.state_database)
                async_http_resource = SharedAsyncHttpClient(
                    AsyncHttpClientDetail(
                        timeout_seconds=AGENT_HTTP_TIMEOUT_SECONDS,
                        max_connections=AGENT_HTTP_MAX_CONNECTIONS,
                        max_keepalive_connections=AGENT_HTTP_MAX_KEEPALIVE_CONNECTIONS,
                    ),
                    tls_context=build_agent_tls_context(
                        deployment_profile=runtime_settings.agent.deployment_profile,
                        development_ca_certificate_path=(
                            runtime_settings.agent.development_ca_certificate_path
                        ),
                    ),
                )
                key_store = WindowsDpapiDeviceKeyStore(
                    root=runtime_settings.agent.state_database.parent / "keys"
                )
                channel = AgentControlChannel(
                    settings=runtime_settings,
                    secret_store=WindowsAgentSecretStore(),
                    connection_ticket_provider=(
                        AgentConnectionTicketProvider(
                            client=async_http_resource.get_client(),
                            control_plane_api_url=runtime_settings.agent.control_plane_api_url,
                            key_store=key_store,
                        )
                        if runtime_settings.protocol.agent_schema_version
                        is CodexConnectionProtocolVersion.V2
                        else None
                    ),
                    workspace_registry=AgentWorkspaceRegistry(
                        [workspace.to_definition() for workspace in runtime_settings.workspaces]
                    ),
                    journal=journal,
                    logger=agent_logger,
                )
                try:
                    await channel.run()
                finally:
                    journal.close()
                    await async_http_resource.close()
        return 0

    async def run_doctor(self, settings: CodexHostAgentSettings) -> int:
        """执行诊断并记录脱敏 JSON。"""

        report = await AgentDoctor(
            settings=settings,
            secret_store=WindowsAgentSecretStore(),
            device_key_store=WindowsDpapiDeviceKeyStore(
                root=settings.agent.state_database.parent / "keys"
            ),
        ).run()
        logger.info("Agent doctor结果：{}", report.model_dump_json())
        return int(report.exit_code)

    async def run_setup(
        self,
        *,
        config_path: Path,
        api_url: str,
        websocket_url: str,
        verification_url: str | None,
        display_name: str,
        workspace_root: Path | None,
        workspace_key: str,
        workspace_name: str,
        agent_version: str,
        codex_version: str,
        schema_digest: str,
        codex_binary: str = DEFAULT_CODEX_BINARY,
        deployment_profile: AgentDeploymentProfile = AgentDeploymentProfile.PRODUCTION,
        development_ca_certificate_path: Path | None = None,
        enrollment_intent_token: str | None = None,
        bootstrap: AgentBootstrapSettings | None = None,
    ) -> int:
        """运行首次授权并写入不含密钥材料的 Agent 配置。"""

        self._validate_codex_prerequisite(codex_version, codex_binary)
        deployment_paths = resolve_agent_deployment_paths(deployment_profile)
        tls_context = build_agent_tls_context(
            deployment_profile=deployment_profile,
            development_ca_certificate_path=development_ca_certificate_path,
        )
        http_resource = SharedAsyncHttpClient(
            AsyncHttpClientDetail(
                timeout_seconds=AGENT_HTTP_TIMEOUT_SECONDS,
                max_connections=AGENT_HTTP_MAX_CONNECTIONS,
                max_keepalive_connections=AGENT_HTTP_MAX_KEEPALIVE_CONNECTIONS,
            ),
            tls_context=tls_context,
        )
        try:
            await CodexAgentSetupUsecase(
                client=http_resource.get_client(),
                key_store=WindowsDpapiDeviceKeyStore(root=deployment_paths.device_key_directory),
                ui=WindowsEnrollmentUi(),
                acl_enforcer=WindowsCurrentUserAclEnforcer(),
            ).execute(
                config_path=config_path,
                api_url=api_url,
                websocket_url=websocket_url,
                verification_url=verification_url,
                display_name=display_name,
                platform="windows",
                expected_codex_version=codex_version,
                codex_binary=codex_binary,
                agent_version=agent_version,
                schema_digest=schema_digest,
                workspace=(
                    AgentWorkspaceSettings(
                        key=workspace_key,
                        display_name=workspace_name,
                        root=workspace_root,
                        allow_write=True,
                    )
                    if workspace_root is not None
                    else None
                ),
                deployment_profile=deployment_profile,
                development_ca_certificate_path=development_ca_certificate_path,
                enrollment_intent_token=enrollment_intent_token,
                default_workspace_key=(
                    bootstrap.default_workspace_key if bootstrap is not None else workspace_key
                ),
                default_workspace_name=(
                    bootstrap.default_workspace_name if bootstrap is not None else workspace_name
                ),
            )
            logger.info("Agent设备授权和本地配置已经完成。")
            return 0
        finally:
            await http_resource.close()

    def run_uri(
        self,
        *,
        config_path: Path,
        bootstrap_path: Path,
        uri: str,
        deployment_profile: AgentDeploymentProfile = AgentDeploymentProfile.PRODUCTION,
    ) -> int:
        """消费自定义 URI 中的一次性 token 并启动计划任务。"""

        token = self._read_enrollment_token(uri, deployment_profile=deployment_profile)
        bootstrap = AgentBootstrapSettingsLoader().load(bootstrap_path)
        bootstrap.validate_deployment_profile(deployment_profile)
        enrollment_lock_path = config_path.parent / "enrollment.lock"
        enrollment_lock_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with portalocker.Lock(
                enrollment_lock_path,
                mode="a",
                timeout=0,
                flags=(portalocker.LockFlags.EXCLUSIVE | portalocker.LockFlags.NON_BLOCKING),
            ):
                if config_path.is_file():
                    self.load_settings(config_path)
                    if deployment_profile is AgentDeploymentProfile.DEVELOPMENT:
                        self._start_scheduled_agent(
                            config_path,
                            deployment_profile=deployment_profile,
                        )
                    else:
                        self._start_scheduled_agent(config_path)
                    WindowsEnrollmentUi().show_info(
                        "这台电脑已经连接。Agent 已启动，不会重复注册设备。"
                    )
                    return 0
                connection = bootstrap.require_connection_for_profile(deployment_profile)
                result = asyncio.run(
                    self.run_setup(
                        config_path=config_path,
                        api_url=connection.api_url,
                        websocket_url=connection.websocket_url,
                        verification_url=connection.verification_url,
                        display_name=platform.node().strip() or DEFAULT_AGENT_DISPLAY_NAME,
                        workspace_root=None,
                        workspace_key=bootstrap.default_workspace_key,
                        workspace_name=bootstrap.default_workspace_name,
                        agent_version=bootstrap.agent_version,
                        codex_version=bootstrap.expected_codex_version,
                        schema_digest=bootstrap.app_server_schema_digest,
                        deployment_profile=deployment_profile,
                        development_ca_certificate_path=(
                            self._resolve_development_ca_certificate_path(bootstrap_path)
                            if deployment_profile is AgentDeploymentProfile.DEVELOPMENT
                            else None
                        ),
                        enrollment_intent_token=token,
                        bootstrap=bootstrap,
                    )
                )
                if result == 0:
                    if deployment_profile is AgentDeploymentProfile.DEVELOPMENT:
                        self._start_scheduled_agent(
                            config_path,
                            deployment_profile=deployment_profile,
                        )
                    else:
                        self._start_scheduled_agent(config_path)
                return result
        except portalocker.exceptions.LockException as exc:
            raise PermissionError("另一项电脑连接操作正在进行，请等待完成后重试。") from exc

    def run_settings(
        self,
        *,
        config_path: Path,
        bootstrap_path: Path,
        deployment_profile: AgentDeploymentProfile = AgentDeploymentProfile.PRODUCTION,
    ) -> int:
        """打开最小设置窗口。"""

        WindowsAgentSettingsWindow(
            config_path=config_path,
            bootstrap=AgentBootstrapSettingsLoader().load(bootstrap_path),
            deployment_profile=deployment_profile,
        ).show()
        return 0

    def run_launcher(
        self,
        *,
        config_path: Path,
        bootstrap_path: Path,
        launch_command: str,
        uri: str | None,
        deployment_profile: AgentDeploymentProfile = AgentDeploymentProfile.PRODUCTION,
    ) -> int:
        """选择可信的较新 Agent，并完整转发稳定安装入口。"""

        bootstrap = AgentBootstrapSettingsLoader().load(bootstrap_path)
        bootstrap.validate_deployment_profile(deployment_profile)
        release = bootstrap.release
        selector = AgentExecutableSelector(
            version_reader=WindowsAgentFileVersionReader(),
            signature_verifier=(
                WindowsAuthenticodeVerifier(
                    allowed_signer_sha256=release.authenticode_signer_sha256_allowlist
                )
                if release is not None
                else None
            ),
        )
        maximum_restarts = 3 if launch_command == AGENT_COMMAND_RUN else 0
        for _ in range(maximum_restarts + 1):
            executable_path = asyncio.run(
                selector.select(
                    installed_executable_path=Path(sys.executable),
                    releases_root=config_path.parent / "releases",
                    bootstrap=bootstrap,
                )
            )
            forwarded_arguments = [
                "--config",
                str(config_path),
                "--bootstrap",
                str(bootstrap_path),
                launch_command,
            ]
            if deployment_profile is AgentDeploymentProfile.DEVELOPMENT:
                forwarded_arguments[0:0] = [
                    "--deployment-profile",
                    deployment_profile.value,
                ]
            if launch_command == AGENT_COMMAND_URI:
                if uri is None:
                    raise ValueError("Agent URI启动入口缺少URI参数。")
                forwarded_arguments.append(uri)
            if executable_path.resolve() == Path(sys.executable).resolve():
                return_code = self.execute(forwarded_arguments)
            else:
                completed = self._subprocess_launcher.run(
                    WindowsSubprocessRequest(
                        argv=(str(executable_path), *forwarded_arguments),
                        timeout_seconds=None,
                        log_category=WindowsSubprocessLogCategory.WINDOWS,
                    )
                )
                return_code = completed.return_code
            if return_code != AGENT_UPDATE_RESTART_EXIT_CODE:
                return return_code
        raise OSError("Agent超过允许的更新重启次数。")

    def execute(self, argv: Sequence[str] | None = None) -> int:
        """执行命令行。"""

        arguments = self.build_argument_parser().parse_args(argv)
        deployment_profile = AgentDeploymentProfile(arguments.deployment_profile)
        deployment_paths = resolve_agent_deployment_paths(deployment_profile)
        config_path = arguments.config or deployment_paths.config_path
        bootstrap_path = arguments.bootstrap or self._default_bootstrap_path()
        command = arguments.command or AGENT_COMMAND_RUN
        self._configure_logging(config_path.parent)
        try:
            if command == AGENT_COMMAND_LAUNCH:
                return self.run_launcher(
                    config_path=config_path,
                    bootstrap_path=bootstrap_path,
                    launch_command=arguments.launch_command,
                    uri=getattr(arguments, "uri", None),
                    deployment_profile=deployment_profile,
                )
            if command == AGENT_COMMAND_SETUP:
                if deployment_profile is AgentDeploymentProfile.DEVELOPMENT:
                    return asyncio.run(
                        self.run_setup(
                            config_path=config_path,
                            api_url=arguments.api_url,
                            websocket_url=arguments.websocket_url,
                            verification_url=arguments.verification_url,
                            display_name=arguments.display_name,
                            workspace_root=arguments.workspace_root,
                            workspace_key=arguments.workspace_key,
                            workspace_name=arguments.workspace_name,
                            agent_version=arguments.agent_version,
                            codex_version=arguments.codex_version,
                            codex_binary=arguments.codex_binary,
                            schema_digest=arguments.schema_digest,
                            deployment_profile=deployment_profile,
                            development_ca_certificate_path=(
                                arguments.development_ca_certificate_path
                            ),
                        )
                    )
                return asyncio.run(
                    self.run_setup(
                        config_path=config_path,
                        api_url=arguments.api_url,
                        websocket_url=arguments.websocket_url,
                        verification_url=arguments.verification_url,
                        display_name=arguments.display_name,
                        workspace_root=arguments.workspace_root,
                        workspace_key=arguments.workspace_key,
                        workspace_name=arguments.workspace_name,
                        agent_version=arguments.agent_version,
                        codex_version=arguments.codex_version,
                        codex_binary=arguments.codex_binary,
                        schema_digest=arguments.schema_digest,
                        development_ca_certificate_path=(arguments.development_ca_certificate_path),
                    )
                )
            if command == AGENT_COMMAND_URI:
                return self.run_uri(
                    config_path=config_path,
                    bootstrap_path=bootstrap_path,
                    uri=arguments.uri,
                    deployment_profile=deployment_profile,
                )
            if command == AGENT_COMMAND_SETTINGS:
                return self.run_settings(
                    config_path=config_path,
                    bootstrap_path=bootstrap_path,
                    deployment_profile=deployment_profile,
                )
            settings = self.load_settings(config_path)
            if settings.agent.deployment_profile is not deployment_profile:
                raise ValueError("Agent配置的deployment_profile与启动参数不一致。")
            if command == AGENT_COMMAND_DOCTOR:
                return asyncio.run(self.run_doctor(settings))
            bootstrap = AgentBootstrapSettingsLoader().load(bootstrap_path)
            bootstrap.validate_deployment_profile(deployment_profile)
            return asyncio.run(
                self.run_agent(
                    settings,
                    config_path=config_path,
                    bootstrap_path=bootstrap_path,
                    bootstrap=bootstrap,
                )
            )
        except KeyboardInterrupt:
            return 130
        except (httpx.HTTPError, OSError, PermissionError, ValueError) as exc:
            logging.getLogger("codex_host_agent").exception("Agent 命令执行失败。")
            interactive_command = command in {
                AGENT_COMMAND_URI,
                AGENT_COMMAND_SETTINGS,
                AGENT_COMMAND_SETUP,
            } or (
                command == AGENT_COMMAND_LAUNCH
                and arguments.launch_command in {AGENT_COMMAND_URI, AGENT_COMMAND_SETTINGS}
            )
            if interactive_command:
                self._show_interactive_error(self._format_interactive_error(exc))
                return AGENT_USER_ERROR_EXIT_CODE
            raise
        return 0

    def _configure_logging(self, state_directory: Path) -> None:
        state_directory.mkdir(parents=True, exist_ok=True)
        log_directory = state_directory / "logs"
        log_directory.mkdir(parents=True, exist_ok=True)
        log_path = (log_directory / "agent.log").resolve()
        agent_logger = logging.getLogger("codex_host_agent")
        agent_logger.setLevel(logging.INFO)
        agent_logger.propagate = False
        rotating_handlers = [
            existing
            for existing in agent_logger.handlers
            if isinstance(existing, logging.handlers.RotatingFileHandler)
        ]
        if any(Path(existing.baseFilename).resolve() == log_path for existing in rotating_handlers):
            return
        for existing in rotating_handlers:
            agent_logger.removeHandler(existing)
            existing.close()
        handler = logging.handlers.RotatingFileHandler(
            log_path,
            maxBytes=AGENT_LOG_MAX_BYTES,
            backupCount=AGENT_LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        agent_logger.addHandler(handler)

    def _validate_codex_prerequisite(self, expected_version: str, codex_binary: str) -> None:
        try:
            command = CodexProcessSupport.resolve_command(codex_binary)
            completed = self._subprocess_launcher.run(
                WindowsSubprocessRequest(
                    argv=(*command, "--version"),
                    environment=CodexProcessSupport.build_standalone_environment(),
                    timeout_seconds=10,
                    log_category=WindowsSubprocessLogCategory.CODEX,
                )
            )
            if completed.return_code != 0:
                raise OSError("Codex CLI版本读取失败。")
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            raise OSError(
                "未找到可用的 Codex CLI。请先安装 Codex CLI，重新登录 Windows 后再连接电脑。"
            ) from exc
        tokens = completed.stdout.strip().split()
        actual_version = tokens[-1] if tokens else ""
        if actual_version != expected_version:
            raise ValueError(
                f"Codex CLI 版本不兼容。需要 {expected_version}，当前为 "
                f"{actual_version or '未知版本'}。"
            )

    def _format_interactive_error(self, error: Exception) -> str:
        if isinstance(error, httpx.TimeoutException):
            return "连接服务器超时，请检查网络后重试。"
        if isinstance(error, httpx.HTTPStatusError):
            status_code = error.response.status_code
            if status_code in {401, 403}:
                return "服务器拒绝了连接请求，请返回网站重新发起电脑连接。"
            if status_code == 409:
                return "该连接请求已使用或状态冲突，请返回网站重新发起。"
            return f"服务器暂时无法完成连接请求（HTTP {status_code}）。"
        if isinstance(error, httpx.RequestError):
            return "无法连接正式服务器，请检查网络和系统时间后重试。"
        return str(error)

    def _show_interactive_error(self, message: str) -> None:
        try:
            WindowsEnrollmentUi().show_error(message)
        except OSError:
            logging.getLogger("codex_host_agent").exception("Agent 错误窗口显示失败。")

    def _default_bootstrap_path(self) -> Path:
        executable_directory = (
            Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path.cwd()
        )
        return executable_directory / AGENT_BOOTSTRAP_FILE_NAME

    @staticmethod
    def _resolve_development_ca_certificate_path(bootstrap_path: Path) -> Path:
        """解析与 Development MSI 同目录的 Caddy 开发 CA 证书。"""

        certificate_path = (
            bootstrap_path.parent / AGENT_DEVELOPMENT_CA_CERTIFICATE_FILE_NAME
        ).resolve()
        if not certificate_path.is_file():
            raise FileNotFoundError("开发Agent安装包缺少 Caddy CA 证书。")
        return certificate_path

    def _read_enrollment_token(
        self,
        uri: str,
        *,
        deployment_profile: AgentDeploymentProfile = AgentDeploymentProfile.PRODUCTION,
    ) -> str:
        parsed = urlparse(uri)
        uri_scheme = resolve_agent_deployment_paths(deployment_profile).uri_scheme
        if parsed.scheme != uri_scheme or parsed.netloc != CODEX_REMOTE_ENROLL_HOST:
            raise ValueError("不支持的Codex Remote URI。")
        query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True)
        if set(query) != {CODEX_REMOTE_TOKEN_QUERY_KEY}:
            raise ValueError("Codex Remote URI只允许携带一次性token。")
        values = query[CODEX_REMOTE_TOKEN_QUERY_KEY]
        if len(values) != 1 or len(values[0]) < 32:
            raise ValueError("Codex Remote URI一次性token无效。")
        return values[0]

    def _start_scheduled_agent(
        self,
        config_path: Path,
        *,
        deployment_profile: AgentDeploymentProfile = AgentDeploymentProfile.PRODUCTION,
    ) -> None:
        WindowsAgentTaskController(
            config_path=config_path,
            deployment_profile=deployment_profile,
        ).start()

    @contextmanager
    def _hold_runtime_profile_resources(self, *, state_directory: Path) -> Iterator[None]:
        """在持有实例锁期间创建 profile 专属目录并清理瞬态 PID 文件。"""

        log_directory = state_directory / "logs"
        temporary_directory = state_directory / "tmp"
        pid_path = state_directory / "agent.pid"
        for directory in (state_directory, log_directory, temporary_directory):
            directory.mkdir(parents=True, exist_ok=True)
        temporary_pid_path = pid_path.with_suffix(".pid.tmp")
        temporary_pid_path.write_text(str(os.getpid()), encoding="ascii")
        temporary_pid_path.replace(pid_path)
        try:
            yield
        finally:
            pid_path.unlink(missing_ok=True)
            temporary_pid_path.unlink(missing_ok=True)

    async def _apply_startup_update(
        self,
        *,
        settings: CodexHostAgentSettings,
        config_path: Path,
        bootstrap_path: Path,
        bootstrap: AgentBootstrapSettings,
        agent_logger: logging.Logger,
    ) -> int | None:
        release = bootstrap.release
        if release is None or not release.enabled:
            return None
        runtime_settings = ArtifactReleaseRuntimeSettings(
            enabled=True,
            trusted_root_path=str(bootstrap_path.parent / release.trusted_root_file_name),
            repository_url=release.repository_url,
            repository_host_allowlist=release.repository_host_allowlist,
            authenticode_signer_sha256_allowlist=(release.authenticode_signer_sha256_allowlist),
            max_download_bytes=release.max_download_bytes,
            request_timeout_seconds=release.request_timeout_seconds,
            staging_root=str(config_path.parent / "releases"),
            retained_versions=release.retained_versions,
            health_timeout_seconds=release.health_timeout_seconds,
            rollback_budget=release.rollback_budget,
            minimum_security_version=release.minimum_security_version,
        )
        runtime = CodexAgentReleaseRuntime.build(runtime_settings)
        try:
            updater = CodexAgentStartupUpdater(
                runtime=runtime,
                manifest_client=CodexAgentReleaseManifestClient(
                    catalog=runtime.catalog,
                ),
                version_policy=AgentVersionPolicy(),
            )
            state = await updater.execute(
                manifest_target_path=release.manifest_target_path,
                current_version=settings.protocol.agent_version,
                minimum_security_version=release.minimum_security_version,
                host_id=settings.agent.host_id,
                health_check=CodexAgentUpdateHealthCheck(
                    config_path=config_path,
                    bootstrap_path=bootstrap_path,
                    timeout_seconds=release.health_timeout_seconds,
                ),
            )
        except PermissionError:
            raise
        except Exception:
            agent_logger.exception("Agent启动更新检查失败，继续运行当前安全版本。")
            return None
        finally:
            await runtime.close()
        if state is AgentStartupUpdateState.UPDATED:
            agent_logger.info("Agent新版本已通过健康检查，将由计划任务重启应用。")
            return AGENT_UPDATE_RESTART_EXIT_CODE
        if state is AgentStartupUpdateState.ROLLED_BACK:
            agent_logger.error("Agent新版本健康检查失败，已恢复上一版本。")
        return None


if __name__ == "__main__":
    raise SystemExit(CodexHostAgentCli().execute())
