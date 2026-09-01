"""Agent 本地与控制面连接诊断。"""

from __future__ import annotations

import asyncio
import socket
import sqlite3
import subprocess
import time
from urllib.parse import urlparse

from src.application.ports.agent_device_key_store_port import AgentDeviceKeyStorePort
from src.core.codex_contract.agent_runtime_health_contract import (
    AgentDoctorCheck,
    AgentDoctorCheckState,
    AgentDoctorExitCode,
    AgentDoctorReport,
)
from src.core.codex_contract.connection_session_contract import CodexConnectionProtocolVersion
from src.infrastructure.codex_agent.agent_configuration import CodexHostAgentSettings
from src.infrastructure.codex_agent.agent_secret_store import (
    AgentSecretNotFoundError,
    AgentSecretStorePort,
)
from src.infrastructure.codex_agent.app_server_process_supervisor import CodexProcessSupport
from src.infrastructure.process.windows_subprocess_launcher import (
    WindowsSubprocessLauncher,
    WindowsSubprocessLogCategory,
    WindowsSubprocessRequest,
)


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

    def _check_state_database(self) -> AgentDoctorCheck:
        path = self._settings.agent.state_database
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(path)
            try:
                connection.execute("PRAGMA quick_check")
            finally:
                connection.close()
            return AgentDoctorCheck(
                name="sqlite",
                state=AgentDoctorCheckState.PASS,
                reason_code="sqlite_ok",
            )
        except sqlite3.Error:
            return AgentDoctorCheck(
                name="sqlite",
                state=AgentDoctorCheckState.FAILED,
                reason_code="sqlite_unavailable",
            )

    def _check_workspaces(self) -> AgentDoctorCheck:
        try:
            for workspace in self._settings.workspaces:
                workspace.root.resolve(strict=True)
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
            return AgentDoctorCheck(
                name="codex_binary",
                state=AgentDoctorCheckState.PASS,
                reason_code="codex_binary_ok",
                detail=(
                    f"实际版本={version}; 旧配置期望值="
                    f"{self._settings.protocol.expected_codex_version}（仅观测）"
                ),
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
            await asyncio.to_thread(socket.getaddrinfo, hostname, parsed.port or 443)
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
            detail=f"耗时{elapsed_ms}毫秒",
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
        if any(item.state == AgentDoctorCheckState.FAILED for item in checks):
            return AgentDoctorExitCode.NETWORK_FAILURE
        if any(item.state == AgentDoctorCheckState.BLOCKED for item in checks):
            return AgentDoctorExitCode.COMPATIBILITY_BLOCKED
        if any(item.state == AgentDoctorCheckState.WARN for item in checks):
            return AgentDoctorExitCode.USER_ACTION_REQUIRED
        return AgentDoctorExitCode.HEALTHY
