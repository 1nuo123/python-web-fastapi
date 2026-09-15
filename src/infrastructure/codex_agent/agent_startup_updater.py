"""Agent 启动阶段的可信更新检查与健康门。"""

from __future__ import annotations

import asyncio
from enum import StrEnum
from pathlib import Path
from uuid import UUID

from src.application.ports.artifact_release_port import TufTargetReaderPort
from src.core.artifact_release_contract.artifact_contract import ArtifactActivationRecord
from src.core.codex_contract.agent_release_manifest_contract import (
    CodexAgentReleaseManifestEnvelope,
    parse_agent_release_version,
)
from src.infrastructure.codex_agent.agent_release_runtime import CodexAgentReleaseRuntime
from src.infrastructure.process.windows_subprocess_launcher import (
    WindowsSubprocessLauncher,
    WindowsSubprocessLogCategory,
    WindowsSubprocessRequest,
)


class AgentStartupUpdateState(StrEnum):
    """Agent 启动更新结果。"""

    CURRENT = "current"
    UPDATED = "updated"
    ROLLED_BACK = "rolled_back"


class AgentVersionPolicy:
    """比较冻结的三段数字版本。"""

    def is_older(self, current: str, target: str) -> bool:
        """判断当前版本是否低于目标版本。"""

        return self._parse(current) < self._parse(target)

    def newest(self, first: str, second: str) -> str:
        """Return the stricter of two security-floor versions."""

        return first if self._parse(first) >= self._parse(second) else second

    def _parse(self, value: str) -> tuple[int, int, int]:
        return parse_agent_release_version(value)


class CodexAgentReleaseManifestClient:
    """通过 python-tuf 读取并验证强类型发布清单 target。"""

    def __init__(
        self,
        *,
        catalog: TufTargetReaderPort,
    ) -> None:
        self._catalog = catalog

    async def read(self, target_path: str) -> CodexAgentReleaseManifestEnvelope:
        """读取并验证发布清单。"""

        content = await self._catalog.read_target(target_path)
        return CodexAgentReleaseManifestEnvelope.model_validate_json(content)


class CodexAgentUpdateHealthCheck:
    """使用新 Agent 执行 doctor，失败时触发原子回滚。"""

    def __init__(
        self,
        *,
        config_path: Path,
        bootstrap_path: Path,
        timeout_seconds: int,
        subprocess_launcher: WindowsSubprocessLauncher | None = None,
    ) -> None:
        self._config_path = config_path
        self._bootstrap_path = bootstrap_path
        self._timeout_seconds = timeout_seconds
        self._subprocess_launcher = subprocess_launcher or WindowsSubprocessLauncher()

    async def __call__(self, record: ArtifactActivationRecord) -> bool:
        """执行新版本脱敏诊断。"""

        return await asyncio.to_thread(self._run_sync, record)

    def _run_sync(self, record: ArtifactActivationRecord) -> bool:
        completed = self._subprocess_launcher.run(
            WindowsSubprocessRequest(
                argv=(
                    str(record.staged_path),
                    "--config",
                    str(self._config_path),
                    "--bootstrap",
                    str(self._bootstrap_path),
                    "doctor",
                ),
                timeout_seconds=self._timeout_seconds,
                log_category=WindowsSubprocessLogCategory.WINDOWS,
            )
        )
        return completed.return_code == 0


class CodexAgentStartupUpdater:
    """在建立控制通道前执行灰度、最低版本和回滚策略。"""

    def __init__(
        self,
        *,
        runtime: CodexAgentReleaseRuntime,
        manifest_client: CodexAgentReleaseManifestClient,
        version_policy: AgentVersionPolicy,
    ) -> None:
        self._runtime = runtime
        self._manifest_client = manifest_client
        self._version_policy = version_policy
        self._last_target_version: str | None = None

    @property
    def last_target_version(self) -> str | None:
        """Last manifest version inspected by this updater instance."""

        return self._last_target_version

    async def execute(
        self,
        *,
        manifest_target_path: str,
        current_version: str,
        minimum_security_version: str,
        host_id: UUID,
        health_check: CodexAgentUpdateHealthCheck,
    ) -> AgentStartupUpdateState:
        """检查并应用一个通过全部信任门的 Agent 更新。"""

        current_is_blocked = self._version_policy.is_older(
            current_version,
            minimum_security_version,
        )
        try:
            manifest = await self._manifest_client.read(manifest_target_path)
            detail = manifest.detail
            self._last_target_version = detail.version
            effective_minimum = self._version_policy.newest(
                minimum_security_version,
                detail.minimum_security_version,
            )
            current_is_blocked = self._version_policy.is_older(
                current_version,
                effective_minimum,
            )
            target_is_newer = self._version_policy.is_older(current_version, detail.version)
            if not target_is_newer:
                if current_is_blocked:
                    raise PermissionError("当前Agent版本低于最低安全版本。")
                return AgentStartupUpdateState.CURRENT
            forced = detail.forced or current_is_blocked
            result = await self._runtime.coordinator.update_agent(
                version=detail.version,
                digest_sha256=detail.digest_sha256,
                target_url=detail.download_url,
                rollout_percent=detail.rollout_percent,
                rollout_subject_digest=host_id.hex,
                forced=forced,
                health_check=health_check,
            )
        except Exception as exc:
            if current_is_blocked:
                raise PermissionError("最低安全版本更新失败，Agent已停止连接。") from exc
            raise
        if result.rollback_performed:
            if current_is_blocked:
                raise PermissionError("最低安全版本健康检查失败，Agent已停止连接。")
            return AgentStartupUpdateState.ROLLED_BACK
        return AgentStartupUpdateState.UPDATED
