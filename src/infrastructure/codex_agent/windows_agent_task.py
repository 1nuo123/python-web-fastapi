"""Windows Agent 当前用户计划任务控制。"""

from __future__ import annotations

import csv
import json
import os
import re
import time
from dataclasses import dataclass
from enum import StrEnum
from io import StringIO
from pathlib import Path
from typing import Final, Protocol

import psutil

from src.infrastructure.codex_agent.agent_deployment_profile import AgentDeploymentProfile
from src.infrastructure.process.windows_subprocess_launcher import (
    WindowsSubprocessLauncher,
    WindowsSubprocessLogCategory,
    WindowsSubprocessRequest,
    WindowsSubprocessResult,
)

CODEX_AGENT_TASK_NAME_PREFIX: Final = "CodexRemoteAgent"
CURRENT_USER_SID_COMMAND: Final = "whoami.exe"
POWERSHELL_EXECUTABLE: Final = "powershell.exe"
WINDOWS_SID_PATTERN: Final = re.compile(r"^S-1-(?:\d+-)+\d+$", re.IGNORECASE)
RUNNING_TASK_STATES: Final = frozenset({"Running", "Queued"})
TASK_CONTROL_TIMEOUT_SECONDS: Final = 15.0
TASK_STATE_POLL_INTERVAL_SECONDS: Final = 0.2
AGENT_RUN_COMMAND: Final = "run"


class AgentLifecycleState(StrEnum):
    """Agent 生命周期状态。"""

    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


READ_TASK_STATUS_SCRIPT: Final = """
$ErrorActionPreference = 'Stop'
$OutputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::new()
$taskName = $env:CODEX_REMOTE_AGENT_TASK_NAME
$task = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
$info = Get-ScheduledTaskInfo -TaskName $taskName -ErrorAction Stop
[pscustomobject]@{
  state = $task.State.ToString()
  last_task_result = [int64]$info.LastTaskResult
} | ConvertTo-Json -Compress
"""
START_TASK_SCRIPT: Final = """
$ErrorActionPreference = 'Stop'
$OutputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::new()
Start-ScheduledTask -TaskName $env:CODEX_REMOTE_AGENT_TASK_NAME -ErrorAction Stop
"""
STOP_TASK_SCRIPT: Final = """
$ErrorActionPreference = 'Stop'
$OutputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::new()
Stop-ScheduledTask -TaskName $env:CODEX_REMOTE_AGENT_TASK_NAME -ErrorAction Stop
"""


class WindowsAgentTaskError(OSError):
    """计划任务不存在、拒绝操作或未在时限内进入目标状态。"""


@dataclass(frozen=True, slots=True)
class WindowsAgentTaskStatus:
    """计划任务可观测状态。"""

    state: str
    last_task_result: int

    @property
    def is_running(self) -> bool:
        return self.state in RUNNING_TASK_STATES


class WindowsAgentTaskBackend(Protocol):
    """计划任务系统调用边界。"""

    def read_status(self, task_name: str) -> WindowsAgentTaskStatus: ...

    def start(self, task_name: str) -> None: ...

    def stop(self, task_name: str) -> None: ...


class WindowsAgentRunProcessBackend(Protocol):
    """停止计划任务启动器遗留的 Agent 运行进程。"""

    def stop_all(self) -> None: ...


class NoopWindowsAgentRunProcessBackend:
    """在未知 Agent 配置路径时保留原有计划任务控制能力。"""

    def stop_all(self) -> None:
        return


class PsutilWindowsAgentRunProcessBackend:
    """只终止属于指定安装配置的 Agent 运行进程。"""

    def __init__(self, *, config_path: Path, executable_path: Path | None = None) -> None:
        self._config_path = self._normalize_path(config_path)
        self._executable_path = self._normalize_path(
            executable_path or config_path.parent / "codex-remote-agent.exe"
        )

    def stop_all(self) -> None:
        processes = list(self._iter_matching_processes())
        denied_process_ids: list[int] = []
        for process in processes:
            try:
                process.terminate()
            except psutil.NoSuchProcess:
                continue
            except psutil.AccessDenied:
                denied_process_ids.append(process.pid)
        if denied_process_ids:
            raise WindowsAgentTaskError(
                "Agent 进程停止被拒绝，进程 ID："
                + ", ".join(str(process_id) for process_id in denied_process_ids)
            )
        _, alive = psutil.wait_procs(processes, timeout=5.0)
        for process in alive:
            try:
                process.kill()
            except psutil.NoSuchProcess:
                continue
            except psutil.AccessDenied as exc:
                raise WindowsAgentTaskError(f"无法终止 Agent 进程 {process.pid}。") from exc
        _, survivors = psutil.wait_procs(alive, timeout=5.0)
        if survivors:
            process_ids = ", ".join(str(process.pid) for process in survivors)
            raise WindowsAgentTaskError(f"Agent 进程停止超时：{process_ids}")

    def _iter_matching_processes(self) -> list[psutil.Process]:
        matched: list[psutil.Process] = []
        for process in psutil.process_iter(["exe", "cmdline"]):
            try:
                executable = process.info["exe"]
                arguments = process.info["cmdline"]
                if executable is None or not arguments:
                    continue
                if self._normalize_path(executable) != self._executable_path:
                    continue
                if self._matches_run_command([str(argument) for argument in arguments]):
                    matched.append(process)
            except (OSError, psutil.AccessDenied, psutil.NoSuchProcess):
                continue
        return matched

    def _matches_run_command(self, arguments: list[str]) -> bool:
        if not arguments or arguments[-1].casefold() != AGENT_RUN_COMMAND:
            return False
        for index, argument in enumerate(arguments[:-1]):
            if argument.casefold() != "--config" or index + 1 >= len(arguments):
                continue
            return self._normalize_path(arguments[index + 1]) == self._config_path
        return False

    @staticmethod
    def _normalize_path(path: str | Path) -> str:
        return os.path.normcase(os.path.abspath(os.fspath(path)))


class PowerShellWindowsAgentTaskBackend:
    """使用 Windows ScheduledTasks 模块控制当前用户任务。"""

    def __init__(self, launcher: WindowsSubprocessLauncher | None = None) -> None:
        self._launcher = launcher or WindowsSubprocessLauncher()

    def read_status(self, task_name: str) -> WindowsAgentTaskStatus:
        completed = self._run(READ_TASK_STATUS_SCRIPT, task_name)
        try:
            payload = json.loads(completed.stdout)
            return WindowsAgentTaskStatus(
                state=str(payload["state"]),
                last_task_result=int(payload["last_task_result"]),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise WindowsAgentTaskError("无法解析 Agent 计划任务状态。") from exc

    def start(self, task_name: str) -> None:
        self._run(START_TASK_SCRIPT, task_name)

    def stop(self, task_name: str) -> None:
        self._run(STOP_TASK_SCRIPT, task_name)

    def _run(
        self,
        script: str,
        task_name: str,
    ) -> WindowsSubprocessResult:
        completed = self._launcher.run(
            WindowsSubprocessRequest(
                argv=(
                    POWERSHELL_EXECUTABLE,
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    script,
                ),
                environment={**os.environ, "CODEX_REMOTE_AGENT_TASK_NAME": task_name},
                timeout_seconds=TASK_CONTROL_TIMEOUT_SECONDS,
                log_category=WindowsSubprocessLogCategory.POWERSHELL,
            )
        )
        if completed.return_code == 0:
            return completed
        detail = completed.stderr.strip() or completed.stdout.strip()
        suffix = f"：{detail}" if detail else "。"
        raise WindowsAgentTaskError(f"Agent 计划任务操作失败{suffix}")


class WindowsAgentTaskIdentityResolver:
    """解析当前 Windows 用户唯一的 Agent 计划任务名。"""

    def __init__(
        self,
        launcher: WindowsSubprocessLauncher | None = None,
        deployment_profile: AgentDeploymentProfile = AgentDeploymentProfile.PRODUCTION,
    ) -> None:
        self._launcher = launcher or WindowsSubprocessLauncher()
        self._deployment_profile = deployment_profile

    def resolve_current_user_task_name(self) -> str:
        """按当前 Windows 用户 SID 生成稳定且互不覆盖的任务名。"""

        completed = self._launcher.run(
            WindowsSubprocessRequest(
                argv=(CURRENT_USER_SID_COMMAND, "/user", "/fo", "csv", "/nh"),
                timeout_seconds=TASK_CONTROL_TIMEOUT_SECONDS,
                log_category=WindowsSubprocessLogCategory.WINDOWS,
            )
        )
        if completed.return_code != 0:
            raise OSError("无法读取当前Windows用户SID。")
        rows = list(csv.reader(StringIO(completed.stdout)))
        if len(rows) != 1 or len(rows[0]) < 2:
            raise OSError("无法解析当前Windows用户SID。")
        sid = rows[0][1].strip()
        if WINDOWS_SID_PATTERN.fullmatch(sid) is None:
            raise OSError("当前Windows用户SID格式无效。")
        profile_suffix = (
            "-Development" if self._deployment_profile is AgentDeploymentProfile.DEVELOPMENT else ""
        )
        return f"{CODEX_AGENT_TASK_NAME_PREFIX}{profile_suffix}-{sid.upper()}"


class WindowsAgentTaskController:
    """提供幂等启动、暂停与可靠重启。"""

    def __init__(
        self,
        *,
        task_name: str | None = None,
        backend: WindowsAgentTaskBackend | None = None,
        config_path: Path | None = None,
        deployment_profile: AgentDeploymentProfile = AgentDeploymentProfile.PRODUCTION,
        run_process_backend: WindowsAgentRunProcessBackend | None = None,
        timeout_seconds: float = TASK_CONTROL_TIMEOUT_SECONDS,
        poll_interval_seconds: float = TASK_STATE_POLL_INTERVAL_SECONDS,
    ) -> None:
        if timeout_seconds <= 0 or poll_interval_seconds <= 0:
            raise ValueError("计划任务等待时间必须大于 0。")
        self._task_name = task_name or (
            WindowsAgentTaskIdentityResolver(
                deployment_profile=deployment_profile
            ).resolve_current_user_task_name()
        )
        self._backend = backend or PowerShellWindowsAgentTaskBackend()
        self._run_process_backend = run_process_backend or (
            PsutilWindowsAgentRunProcessBackend(config_path=config_path)
            if config_path is not None
            else NoopWindowsAgentRunProcessBackend()
        )
        self._timeout_seconds = timeout_seconds
        self._poll_interval_seconds = poll_interval_seconds
        self._lifecycle_state = AgentLifecycleState.STOPPED

    @property
    def lifecycle_state(self) -> AgentLifecycleState:
        """读取当前控制器观察到的 Agent 生命周期状态。"""

        return self._lifecycle_state

    def read_status(self) -> WindowsAgentTaskStatus:
        return self._backend.read_status(self._task_name)

    def start(self) -> WindowsAgentTaskStatus:
        self._lifecycle_state = AgentLifecycleState.STARTING
        try:
            status = self.read_status()
            if status.is_running:
                self._lifecycle_state = AgentLifecycleState.RUNNING
                return status
            if status.state == "Disabled":
                raise WindowsAgentTaskError("Agent 计划任务已禁用，请重新安装 Agent。")
            self._backend.start(self._task_name)
            status = self._wait_for_running(expected_running=True, action="启动")
            self._lifecycle_state = AgentLifecycleState.RUNNING
            return status
        except OSError:
            self._lifecycle_state = AgentLifecycleState.FAILED
            raise

    def pause(self) -> WindowsAgentTaskStatus:
        self._lifecycle_state = AgentLifecycleState.STOPPING
        try:
            status = self.read_status()
            if status.is_running:
                self._backend.stop(self._task_name)
                status = self._wait_for_running(expected_running=False, action="暂停")
            self._run_process_backend.stop_all()
            self._lifecycle_state = AgentLifecycleState.PAUSED
            return status
        except OSError:
            self._lifecycle_state = AgentLifecycleState.FAILED
            raise

    def restart(self) -> WindowsAgentTaskStatus:
        self.pause()
        self._lifecycle_state = AgentLifecycleState.STARTING
        try:
            self._backend.start(self._task_name)
            status = self._wait_for_running(expected_running=True, action="重启")
            self._lifecycle_state = AgentLifecycleState.RUNNING
            return status
        except OSError:
            self._lifecycle_state = AgentLifecycleState.FAILED
            raise

    def stop(self) -> WindowsAgentTaskStatus:
        """幂等停止计划任务和残留 worker。"""

        status = self.pause()
        self._lifecycle_state = AgentLifecycleState.STOPPED
        return status

    def _wait_for_running(
        self,
        *,
        expected_running: bool,
        action: str,
    ) -> WindowsAgentTaskStatus:
        deadline = time.monotonic() + self._timeout_seconds
        status = self.read_status()
        while status.is_running is not expected_running:
            if time.monotonic() >= deadline:
                target = "运行" if expected_running else "暂停"
                raise WindowsAgentTaskError(f"Agent {action}超时，计划任务未进入{target}状态。")
            time.sleep(self._poll_interval_seconds)
            status = self.read_status()
        return status
