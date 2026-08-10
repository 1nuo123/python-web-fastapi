"""启动 Windows Codex Host Agent。"""

from __future__ import annotations

import argparse
import asyncio
import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Final

import portalocker
from loguru import logger

from src.core.codex_contract.connection_session_contract import (
    CodexConnectionProtocolVersion,
)
from src.core.http_contract.outbound_http_client_contract import AsyncHttpClientDetail
from src.infrastructure.codex_agent.agent_command_journal import AgentCommandJournal
from src.infrastructure.codex_agent.agent_configuration import (
    AgentWorkspaceSettings,
    CodexHostAgentSettings,
    CodexHostAgentSettingsLoader,
)
from src.infrastructure.codex_agent.agent_connection_ticket_provider import (
    AgentConnectionTicketProvider,
)
from src.infrastructure.codex_agent.agent_control_channel import AgentControlChannel
from src.infrastructure.codex_agent.agent_doctor import AgentDoctor
from src.infrastructure.codex_agent.agent_secret_store import WindowsAgentSecretStore
from src.infrastructure.codex_agent.agent_setup import (
    CodexAgentSetupUsecase,
    WindowsEnrollmentUi,
)
from src.infrastructure.codex_agent.agent_workspace_registry import (
    AgentWorkspaceRegistry,
    WindowsAgentConfigPermissionVerifier,
)
from src.infrastructure.codex_agent.windows_dpapi_device_key_store import (
    WindowsCurrentUserAclEnforcer,
    WindowsDpapiDeviceKeyStore,
)
from src.infrastructure.resource_slot.shared_async_http_client import SharedAsyncHttpClient

DEFAULT_AGENT_CONFIG_PATH: Final = (
    Path.home() / "AppData" / "Local" / "CodexRemoteAgent" / "agent.toml"
)
AGENT_COMMAND_RUN: Final[str] = "run"
AGENT_COMMAND_DOCTOR: Final[str] = "doctor"
AGENT_COMMAND_SETUP: Final[str] = "setup"
AGENT_HTTP_TIMEOUT_SECONDS = 30
AGENT_HTTP_MAX_CONNECTIONS = 8
AGENT_HTTP_MAX_KEEPALIVE_CONNECTIONS = 4


class CodexHostAgentCli:
    """Agent 运行与诊断命令行入口。"""

    def build_argument_parser(self) -> argparse.ArgumentParser:
        """构建带子命令的参数解析器。"""

        parser = argparse.ArgumentParser(description="运行 Windows Codex 远程控制 Agent")
        parser.add_argument("--config", type=Path, default=DEFAULT_AGENT_CONFIG_PATH)
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
        setup_parser.add_argument("--codex-version", required=True)
        setup_parser.add_argument("--schema-digest", required=True)
        return parser

    def load_settings(self, config_path: Path) -> CodexHostAgentSettings:
        """按统一权限校验器加载强类型配置。"""

        return CodexHostAgentSettingsLoader(WindowsAgentConfigPermissionVerifier()).load(
            config_path
        )

    async def run_agent(self, settings: CodexHostAgentSettings) -> None:
        """加载本地资源并持有单实例锁运行 Agent。"""

        lock_path = settings.agent.state_database.with_suffix(".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        agent_logger = logging.getLogger("codex_host_agent")
        agent_logger.info(
            "启动 Codex Host Agent，工作区：%s",
            [workspace.display_name for workspace in settings.workspaces],
        )
        with portalocker.Lock(
            lock_path,
            mode="a",
            timeout=0,
            flags=portalocker.LockFlags.EXCLUSIVE | portalocker.LockFlags.NON_BLOCKING,
        ):
            journal = AgentCommandJournal(settings.agent.state_database)
            async_http_resource = SharedAsyncHttpClient(
                AsyncHttpClientDetail(
                    timeout_seconds=AGENT_HTTP_TIMEOUT_SECONDS,
                    max_connections=AGENT_HTTP_MAX_CONNECTIONS,
                    max_keepalive_connections=AGENT_HTTP_MAX_KEEPALIVE_CONNECTIONS,
                )
            )
            key_store = WindowsDpapiDeviceKeyStore(
                root=settings.agent.state_database.parent / "keys"
            )
            channel = AgentControlChannel(
                settings=settings,
                secret_store=WindowsAgentSecretStore(),
                connection_ticket_provider=(
                    AgentConnectionTicketProvider(
                        client=async_http_resource.get_client(),
                        control_plane_api_url=settings.agent.control_plane_api_url,
                        key_store=key_store,
                    )
                    if settings.protocol.agent_schema_version is CodexConnectionProtocolVersion.V2
                    else None
                ),
                workspace_registry=AgentWorkspaceRegistry(
                    [workspace.to_definition() for workspace in settings.workspaces]
                ),
                journal=journal,
                logger=agent_logger,
            )
            try:
                await channel.run()
            finally:
                journal.close()
                await async_http_resource.close()

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
        workspace_root: Path,
        workspace_key: str,
        workspace_name: str,
        codex_version: str,
        schema_digest: str,
    ) -> int:
        """运行首次授权并写入不含密钥材料的 Agent 配置。"""

        http_resource = SharedAsyncHttpClient(
            AsyncHttpClientDetail(
                timeout_seconds=AGENT_HTTP_TIMEOUT_SECONDS,
                max_connections=AGENT_HTTP_MAX_CONNECTIONS,
                max_keepalive_connections=AGENT_HTTP_MAX_KEEPALIVE_CONNECTIONS,
            )
        )
        try:
            await CodexAgentSetupUsecase(
                client=http_resource.get_client(),
                key_store=WindowsDpapiDeviceKeyStore(root=config_path.parent / "keys"),
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
                schema_digest=schema_digest,
                workspace=AgentWorkspaceSettings(
                    key=workspace_key,
                    display_name=workspace_name,
                    root=workspace_root,
                    allow_write=True,
                ),
            )
            logger.info("Agent设备授权和本地配置已经完成。")
            return 0
        finally:
            await http_resource.close()

    def execute(self, argv: Sequence[str] | None = None) -> int:
        """执行命令行。"""

        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
        arguments = self.build_argument_parser().parse_args(argv)
        command = arguments.command or AGENT_COMMAND_RUN
        try:
            if command == AGENT_COMMAND_SETUP:
                return asyncio.run(
                    self.run_setup(
                        config_path=arguments.config,
                        api_url=arguments.api_url,
                        websocket_url=arguments.websocket_url,
                        verification_url=arguments.verification_url,
                        display_name=arguments.display_name,
                        workspace_root=arguments.workspace_root,
                        workspace_key=arguments.workspace_key,
                        workspace_name=arguments.workspace_name,
                        codex_version=arguments.codex_version,
                        schema_digest=arguments.schema_digest,
                    )
                )
            settings = self.load_settings(arguments.config)
            if command == AGENT_COMMAND_DOCTOR:
                return asyncio.run(self.run_doctor(settings))
            asyncio.run(self.run_agent(settings))
        except KeyboardInterrupt:
            return 130
        return 0


if __name__ == "__main__":
    raise SystemExit(CodexHostAgentCli().execute())
