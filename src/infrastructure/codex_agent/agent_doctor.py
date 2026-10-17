"""Agent 本地与控制面连接诊断。"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import sqlite3
import subprocess
import time
from urllib.parse import urlparse

import httpx

from src.application.ports.agent_device_key_store_port import AgentDeviceKeyStorePort
from src.core.codex_contract.agent_runtime_health_contract import (
    AgentDoctorCheck,
    AgentDoctorCheckState,
    AgentDoctorExitCode,
    AgentDoctorReport,
)
from src.core.codex_contract.app_server_jsonrpc_contract import AppServerRpcError
from src.core.codex_contract.connection_session_contract import CodexConnectionProtocolVersion
from src.core.http_contract.outbound_http_client_contract import AsyncHttpClientDetail
from src.infrastructure.codex_agent.agent_configuration import (
    CodexHostAgentSettings,
)
from src.infrastructure.codex_agent.agent_connection_policy import AgentControlConnectionPolicy
from src.infrastructure.codex_agent.agent_network_policy import AgentNetworkPolicy
from src.infrastructure.codex_agent.agent_runtime_status_store import AgentRuntimeStatusStore
from src.infrastructure.codex_agent.agent_secret_store import (
    AgentSecretNotFoundError,
    AgentSecretStorePort,
)
from src.infrastructure.codex_agent.app_server_model_catalog import read_model_catalog
from src.infrastructure.codex_agent.app_server_process_supervisor import (
    AppServerProcessSupervisor,
    CodexProcessSupport,
)
from src.infrastructure.process.windows_subprocess_launcher import (
    WindowsSubprocessLauncher,
    WindowsSubprocessLogCategory,
    WindowsSubprocessRequest,
)
from src.infrastructure.resource_slot.shared_async_http_client import SharedAsyncHttpClient


class AgentDoctor:
    """以只读探测为主、默认不输出敏感值的诊断器。"""

    def __init__(
        self,
        *,
        settings: CodexHostAgentSettings,
        secret_store: AgentSecretStorePort | None = None,
        device_key_store: AgentDeviceKeyStorePort | None = None,
        subprocess_launcher: WindowsSubprocessLauncher | None = None,
    ) -> None:
        self._settings = settings
        self._secret_store = secret_store
        self._device_key_store = device_key_store
        self._subprocess_launcher = subprocess_launcher or WindowsSubprocessLauncher()

    async def run(self) -> AgentDoctorReport:
        """执行本地版本、SQLite、目录、DPAPI 与控制面 DNS 检查。"""

        checks = [
            self._check_state_database(),
            self._check_workspaces(),
            self._check_codex_binary(),
            self._check_secret_store(),
            await self._check_control_plane_dns(),
            await self._check_local_protocol(),
            await self._check_control_plane_service(),
            self._check_runtime(),
            AgentDoctorCheck(
                name="device_authentication",
                state=AgentDoctorCheckState.WARN,
                reason_code="device_identity_not_probed",
                detail="只读诊断未签发票据、未替换WSS连接；完整鉴权和升级由正常run入口执行。",
            ),
        ]
        exit_code = self._choose_exit_code(tuple(checks))
        codex_version = self._read_codex_version_safely()
        return AgentDoctorReport(
            agent_version=self._settings.protocol.agent_version,
            codex_version=codex_version,
            schema_digest=self._settings.protocol.app_server_schema_digest,
            state_database=self._settings.agent.state_database,
            checks=tuple(checks),
            exit_code=exit_code,
        )

    async def _check_local_protocol(self) -> AgentDoctorCheck:
        async def ignore(*_args: object) -> None:
            return None

        try:
            supervisor = AppServerProcessSupervisor(
                codex_binary=self._settings.agent.codex_binary,
                allowed_versions=[self._settings.protocol.expected_codex_version],
                max_line_bytes=self._settings.agent.max_app_server_line_bytes,
                allow_experimental_api=self._settings.protocol.allow_experimental_api,
                notification_handler=ignore,
                request_handler=ignore,
                warning_handler=ignore,
                logger=logging.getLogger(__name__),
            )
            try:
                handle = await supervisor.start()
                catalog = await read_model_catalog(handle.client)
                config = await handle.client.request(
                    "config/read",
                    {"cwd": str(self._settings.workspaces[0].root), "includeLayers": False},
                    timeout_seconds=10,
                )
                account = await handle.client.request(
                    "account/read", {"refreshToken": False}, timeout_seconds=10
                )
                if (
                    catalog.state != "ready"
                    or not isinstance(config, dict)
                    or not isinstance(config.get("config"), dict)
                ):
                    raise ValueError("本机有效配置或模型目录不可读。")
                if not isinstance(account, dict):
                    raise ValueError("本机账号状态不可读。")
                if account.get("requiresOpenaiAuth") is True and account.get("account") is None:
                    return AgentDoctorCheck(
                        name="app_server",
                        state=AgentDoctorCheckState.BLOCKED,
                        reason_code="codex_account_required",
                        detail="请先在本机 Codex 完成登录；Agent 不修改登录状态。",
                    )
                return AgentDoctorCheck(
                    name="app_server",
                    state=AgentDoctorCheckState.PASS,
                    reason_code="app_server_ready",
                    detail="初始化、配置、模型和账号状态可读；未执行模型任务。",
                )
            finally:
                await supervisor.stop()
        except (OSError, RuntimeError, ValueError, AppServerRpcError) as exc:
            return AgentDoctorCheck(
                name="app_server",
                state=AgentDoctorCheckState.BLOCKED,
                reason_code="app_server_unavailable",
                detail=f"本机协议检查失败：{type(exc).__name__}，请检查已有 CLI 配置。",
            )

    def _check_runtime(self) -> AgentDoctorCheck:
        status = AgentRuntimeStatusStore(self._settings.agent.state_database).read()
        running = status is not None and status.connection_state not in (None, "stopped")
        return AgentDoctorCheck(
            name="agent_process",
            state=AgentDoctorCheckState.PASS if running else AgentDoctorCheckState.WARN,
            reason_code="agent_running" if running else "agent_not_running",
            detail="进程身份和投影新鲜度已核对；连接状态不等于执行能力。",
        )

    async def _check_control_plane_service(self) -> AgentDoctorCheck:
        network = AgentNetworkPolicy(self._settings.agent)
        url = self._settings.agent.control_plane_api_url
        resource = SharedAsyncHttpClient(
            AsyncHttpClientDetail(
                timeout_seconds=15, max_connections=2, max_keepalive_connections=1
            ),
            tls_context=network.tls_context,
            proxy=network.proxy_for(url),
            trust_env=False,
        )
        try:
            response = await resource.get_client().head(url)
            if response.status_code >= 500:
                response.raise_for_status()
            return AgentDoctorCheck(
                name="control_plane_https",
                state=(
                    AgentDoctorCheckState.WARN
                    if response.status_code in (401, 403)
                    else AgentDoctorCheckState.PASS
                ),
                reason_code="https_reachable",
                detail=f"{network.describe(url)}；HTTP {response.status_code}，仅证明HTTPS服务可达，未证明WSS鉴权。",
            )
        except (httpx.HTTPError, OSError, ValueError) as exc:
            issue = AgentControlConnectionPolicy.issue(exc)
            return AgentDoctorCheck(
                name="control_plane_https",
                state=AgentDoctorCheckState.FAILED,
                reason_code=issue.value,
                detail=f"{network.describe(url)}；{AgentControlConnectionPolicy.describe(exc)}，根路径拒绝不代表设备凭据失效。",
            )
        finally:
            await resource.close()

    def _check_state_database(self) -> AgentDoctorCheck:
        path = self._settings.agent.state_database
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(path)
            try:
                result = connection.execute("PRAGMA quick_check").fetchall()
                if not result or any(str(row[0]).casefold() != "ok" for row in result):
                    return AgentDoctorCheck(
                        name="sqlite",
                        state=AgentDoctorCheckState.BLOCKED,
                        reason_code="sqlite_integrity_failed",
                    )
            finally:
                connection.close()
            return AgentDoctorCheck(
                name="sqlite",
                state=AgentDoctorCheckState.PASS,
                reason_code="sqlite_ok",
            )
        except (sqlite3.Error, OSError):
            return AgentDoctorCheck(
                name="sqlite",
                state=AgentDoctorCheckState.FAILED,
                reason_code="sqlite_unavailable",
            )

    def _check_workspaces(self) -> AgentDoctorCheck:
        try:
            for workspace in self._settings.workspaces:
                root = workspace.root.resolve(strict=True)
                if not root.is_dir():
                    raise NotADirectoryError(str(root))
                with os.scandir(root) as entries:
                    next(entries, None)
                if workspace.allow_write and not os.access(root, os.W_OK):
                    raise PermissionError("项目目录没有所需写入权限。")
            return AgentDoctorCheck(
                name="workspace_policy",
                state=AgentDoctorCheckState.PASS,
                reason_code="workspace_policy_ok",
            )
        except OSError:
            return AgentDoctorCheck(
                name="workspace_policy",
                state=AgentDoctorCheckState.WARN,
                reason_code="workspace_root_unavailable",
            )

    def _check_codex_binary(self) -> AgentDoctorCheck:
        try:
            version = self._read_codex_version()
            if version != self._settings.protocol.expected_codex_version:
                return AgentDoctorCheck(
                    name="codex_binary",
                    state=AgentDoctorCheckState.WARN,
                    reason_code="codex_version_unreviewed",
                )
            return AgentDoctorCheck(
                name="codex_binary",
                state=AgentDoctorCheckState.PASS,
                reason_code="codex_binary_ok",
            )
        except (OSError, subprocess.SubprocessError, ValueError):
            return AgentDoctorCheck(
                name="codex_binary",
                state=AgentDoctorCheckState.BLOCKED,
                reason_code="codex_binary_unavailable",
            )

    def _check_secret_store(self) -> AgentDoctorCheck:
        if self._settings.protocol.agent_schema_version is CodexConnectionProtocolVersion.V2:
            if self._device_key_store is None or self._settings.agent.key_id is None:
                return AgentDoctorCheck(
                    name="dpapi",
                    state=AgentDoctorCheckState.WARN,
                    reason_code="device_key_not_probed",
                )
            try:
                self._device_key_store.read_public_key(self._settings.agent.key_id)
            except (OSError, KeyError, ValueError):
                return AgentDoctorCheck(
                    name="dpapi",
                    state=AgentDoctorCheckState.BLOCKED,
                    reason_code="device_key_unavailable",
                )
            return AgentDoctorCheck(
                name="dpapi",
                state=AgentDoctorCheckState.PASS,
                reason_code="device_key_available",
            )
        if self._secret_store is None or self._settings.agent.legacy_credential_id is None:
            return AgentDoctorCheck(
                name="dpapi",
                state=AgentDoctorCheckState.WARN,
                reason_code="credential_not_probed",
            )
        try:
            self._secret_store.read(self._settings.agent.legacy_credential_id)
        except (AgentSecretNotFoundError, OSError, KeyError, ValueError):
            return AgentDoctorCheck(
                name="dpapi",
                state=AgentDoctorCheckState.BLOCKED,
                reason_code="credential_unavailable",
            )
        return AgentDoctorCheck(
            name="dpapi",
            state=AgentDoctorCheckState.PASS,
            reason_code="credential_available",
        )

    async def _check_control_plane_dns(self) -> AgentDoctorCheck:
        parsed = urlparse(self._settings.agent.control_plane_url)
        hostname = parsed.hostname
        if not hostname:
            return AgentDoctorCheck(
                name="control_plane_dns",
                state=AgentDoctorCheckState.FAILED,
                reason_code="control_plane_url_invalid",
            )
        started = time.monotonic()
        try:
            await asyncio.wait_for(
                asyncio.to_thread(socket.getaddrinfo, hostname, parsed.port or 443), timeout=10
            )
        except OSError:
            return AgentDoctorCheck(
                name="control_plane_dns",
                state=AgentDoctorCheckState.FAILED,
                reason_code="control_plane_dns_failed",
            )
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return AgentDoctorCheck(
            name="control_plane_dns",
            state=AgentDoctorCheckState.PASS,
            reason_code="control_plane_dns_ok",
            detail=f"本机DNS耗时{elapsed_ms}毫秒；代理可能使用远端DNS，不代表TLS或WSS已通过。",
        )

    def _read_codex_version_safely(self) -> str | None:
        try:
            return self._read_codex_version()
        except (OSError, subprocess.SubprocessError, ValueError):
            return None

    def _read_codex_version(self) -> str:
        command = CodexProcessSupport.resolve_command(self._settings.agent.codex_binary)
        completed = self._subprocess_launcher.run(
            WindowsSubprocessRequest(
                argv=(*command, "--version"),
                environment=CodexProcessSupport.build_standalone_environment(),
                timeout_seconds=10,
                log_category=WindowsSubprocessLogCategory.CODEX,
            )
        )
        if completed.return_code != 0:
            raise OSError("本机Codex版本读取失败。")
        tokens = completed.stdout.strip().split()
        if not tokens:
            raise ValueError("本机Codex未返回版本。")
        return tokens[-1]

    def _choose_exit_code(self, checks: tuple[AgentDoctorCheck, ...]) -> AgentDoctorExitCode:
        if any(
            item.state == AgentDoctorCheckState.FAILED
            and item.name in {"control_plane_dns", "control_plane_https", "device_authentication"}
            for item in checks
        ):
            return AgentDoctorExitCode.NETWORK_FAILURE
        if any(item.state == AgentDoctorCheckState.BLOCKED for item in checks):
            return AgentDoctorExitCode.COMPATIBILITY_BLOCKED
        if any(
            item.state in {AgentDoctorCheckState.WARN, AgentDoctorCheckState.FAILED}
            and item.reason_code != "device_identity_not_probed"
            for item in checks
        ):
            return AgentDoctorExitCode.USER_ACTION_REQUIRED
        return AgentDoctorExitCode.HEALTHY
