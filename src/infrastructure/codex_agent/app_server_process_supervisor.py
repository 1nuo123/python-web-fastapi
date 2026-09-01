"""Windows Agent 的 Codex App Server 子进程监督器。"""

from __future__ import annotations

import asyncio
import gc
import hashlib
import logging
import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Literal, cast
from uuid import uuid4

from pydantic import JsonValue

from src.core.codex_contract.agent_diagnostic_contract import (
    AgentDiagnosticCode,
    AgentDiagnosticEnvelope,
    AgentDiagnosticHeader,
    AgentProcessExitDiagnosticDetail,
    AgentStderrDiagnosticDetail,
)
from src.core.codex_contract.app_server_capability_contract import AppServerCapabilityProbeResult
from src.core.codex_contract.app_server_jsonrpc_contract import (
    AppServerLineReaderPort,
    AppServerMessageTooLargeError,
)
from src.infrastructure.codex_agent.app_server_jsonrpc_client import (
    AppServerJsonRpcClient,
    AppServerNotificationHandler,
    AppServerRequestHandler,
    AppServerWarningHandler,
    BoundedAppServerLineReader,
)
from src.infrastructure.process.windows_subprocess_launcher import (
    WindowsAppServerProcessExtension,
    WindowsSubprocessLauncher,
    WindowsSubprocessLogCategory,
    WindowsSubprocessRequest,
)

CODEX_PARENT_PROCESS_VARIABLES: Final = frozenset(
    {
        "CODEX_CI",
        # Codex Desktop 注入的路径可能指向另一套 alpha CLI。Agent 必须
        # 只使用自身配置解析出的 codex 入口，避免开发/生产串环境。
        "CODEX_CLI_PATH",
        "CODEX_INTERNAL_ORIGINATOR_OVERRIDE",
        "CODEX_SHELL",
        "CODEX_THREAD_ID",
    }
)
UNBOUND_AGENT_DIAGNOSTIC_HOST_ID: Final = "unbound"


class CodexProcessSupport:
    """Codex 子进程入口、环境与 Windows transport 的共享支持。"""

    @staticmethod
    def build_standalone_environment() -> dict[str, str]:
        """移除父 Codex 进程注入的嵌套运行变量。"""

        environment = dict(os.environ)
        for variable_name in CODEX_PARENT_PROCESS_VARIABLES:
            environment.pop(variable_name, None)
        return environment

    @staticmethod
    def resolve_command(codex_binary: str) -> tuple[str, ...]:
        """冻结 Codex 入口；Windows npm shim 直接解析为 node 脚本。"""

        resolved = shutil.which(codex_binary)
        if resolved is None:
            raise FileNotFoundError(f"找不到Codex可执行入口：{codex_binary}")
        resolved_path = Path(resolved)
        npm_entry = resolved_path.parent / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
        if resolved_path.suffix.casefold() in {".cmd", ".bat"} and npm_entry.is_file():
            node_binary = shutil.which("node")
            if node_binary is None:
                raise FileNotFoundError("Codex npm入口存在，但找不到Node.js。")
            return node_binary, str(npm_entry)
        return (resolved,)

    @staticmethod
    def close_windows_subprocess_transport(process: asyncio.subprocess.Process) -> None:
        """规避 Python 3.11 Proactor 延迟析构管道的问题。"""

        if os.name != "nt":
            return
        transport = getattr(process, "_transport", None)
        if transport is not None:
            transport.close()


class AppServerVersionMismatchError(RuntimeError):
    """保留旧异常类型，版本不再由 supervisor 启动前硬阻断。"""


@dataclass(frozen=True, slots=True)
class AppServerProcessHandle:
    """一个 App Server 进程代次及其 JSON-RPC 客户端。"""

    instance_id: str
    codex_version: str
    process: asyncio.subprocess.Process
    client: AppServerJsonRpcClient
    initialize_result: JsonValue
    probe_result: AppServerCapabilityProbeResult | None = None


class AppServerProcessSupervisor:
    """读取版本、启动 stdio App Server 并负责有序关闭。"""

    def __init__(
        self,
        *,
        codex_binary: str,
        allowed_versions: list[str],
        max_line_bytes: int,
        notification_handler: AppServerNotificationHandler,
        request_handler: AppServerRequestHandler,
        warning_handler: AppServerWarningHandler,
        logger: logging.Logger,
        host_id: str = UNBOUND_AGENT_DIAGNOSTIC_HOST_ID,
        subprocess_launcher: WindowsSubprocessLauncher | None = None,
    ) -> None:
        self._codex_binary = codex_binary
        self._codex_command = CodexProcessSupport.resolve_command(codex_binary)
        # Deprecated compatibility input. Capability policy owns decisions
        # after initialize; keeping the argument preserves old callers.
        self._allowed_versions = list(allowed_versions)
        self._max_line_bytes = max_line_bytes
        self._notification_handler = notification_handler
        self._request_handler = request_handler
        self._warning_handler = warning_handler
        self._logger = logger
        self._host_id = host_id
        self._subprocess_launcher = subprocess_launcher or WindowsSubprocessLauncher()
        self._handle: AppServerProcessHandle | None = None
        self._stderr_task: asyncio.Task[None] | None = None

    @property
    def handle(self) -> AppServerProcessHandle:
        """读取已启动进程句柄。"""

        if self._handle is None:
            raise RuntimeError("App Server尚未启动。")
        return self._handle

    async def start(self) -> AppServerProcessHandle:
        """启动新进程代次并完成 initialize/initialized。"""

        if self._handle is not None:
            raise RuntimeError("App Server监督器不能重复启动。")
        codex_version = await self._read_codex_version()
        process = await self._subprocess_launcher.create_async(
            WindowsSubprocessRequest(
                argv=(*self._codex_command, "app-server", "--stdio"),
                environment=CodexProcessSupport.build_standalone_environment(),
                stream_limit_bytes=self._max_line_bytes + 1,
                log_category=WindowsSubprocessLogCategory.CODEX,
                extension=WindowsAppServerProcessExtension(),
            ),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        if process.stdin is None or process.stdout is None or process.stderr is None:
            process.kill()
            await process.wait()
            raise RuntimeError("App Server stdio管道创建失败。")
        client = AppServerJsonRpcClient(
            reader=BoundedAppServerLineReader(
                process.stdout,
                max_line_bytes=self._max_line_bytes,
            ),
            writer=process.stdin,
            max_line_bytes=self._max_line_bytes,
            notification_handler=self._notification_handler,
            request_handler=self._request_handler,
            warning_handler=self._warning_handler,
        )
        instance_id = str(uuid4())
        self._stderr_task = asyncio.create_task(
            self._drain_stderr(
                BoundedAppServerLineReader(
                    process.stderr,
                    max_line_bytes=self._max_line_bytes,
                ),
                instance_id=instance_id,
                process_id=process.pid,
                codex_version=codex_version,
            )
        )
        provisional_handle = AppServerProcessHandle(
            instance_id=instance_id,
            codex_version=codex_version,
            process=process,
            client=client,
            initialize_result=None,
        )
        # App Server may emit notifications while initialize is in flight. Publish
        # the process identity first so callbacks can bind those events safely.
        self._handle = provisional_handle
        try:
            await client.start()
            initialize_result = await client.initialize()
        except BaseException:
            self._handle = None
            await client.close()
            process.kill()
            await process.wait()
            await self._stop_stderr_task()
            raise
        self._handle = AppServerProcessHandle(
            instance_id=instance_id,
            codex_version=codex_version,
            process=process,
            client=client,
            initialize_result=initialize_result,
        )
        return self._handle

    async def stop(self, *, grace_seconds: float = 3.0) -> None:
        """停止接受 RPC 后关闭客户端，并在宽限期后终止子进程。"""

        handle = self._handle
        self._handle = None
        if handle is None:
            await self._stop_stderr_task()
            return
        if handle.process.stdin is not None and not handle.process.stdin.is_closing():
            handle.process.stdin.close()
            try:
                await handle.process.stdin.wait_closed()
            except (BrokenPipeError, ConnectionResetError):
                pass
        if handle.process.returncode is None:
            try:
                await asyncio.wait_for(handle.process.wait(), timeout=grace_seconds)
            except TimeoutError:
                handle.process.terminate()
                try:
                    await asyncio.wait_for(handle.process.wait(), timeout=grace_seconds)
                except TimeoutError:
                    handle.process.kill()
                    await handle.process.wait()
        await asyncio.sleep(0)
        await handle.client.close()
        await self._stop_stderr_task()
        if handle.process.returncode not in {None, 0}:
            self._logger.warning(
                AgentDiagnosticEnvelope(
                    header=AgentDiagnosticHeader(
                        detail_kind=AgentDiagnosticCode.APP_SERVER_EXIT_NON_ZERO,
                        host_id=self._host_id,
                        app_server_instance_id=handle.instance_id,
                        process_id=handle.process.pid,
                        codex_version=handle.codex_version,
                        occurred_at=datetime.now(UTC),
                    ),
                    detail=AgentProcessExitDiagnosticDetail(exit_code=handle.process.returncode),
                ).to_log_line()
            )
        CodexProcessSupport.close_windows_subprocess_transport(handle.process)
        del handle
        gc.collect()
        await asyncio.sleep(0)

    async def restart(self) -> AppServerProcessHandle:
        """显式创建新 App Server 代次；旧审批 RPC id 随旧客户端失效。"""

        await self.stop()
        return await self.start()

    async def _read_codex_version(self) -> str:
        """读取规范化的语义版本字符串。"""

        result = await self._subprocess_launcher.run_async(
            WindowsSubprocessRequest(
                argv=(*self._codex_command, "--version"),
                environment=CodexProcessSupport.build_standalone_environment(),
                log_category=WindowsSubprocessLogCategory.CODEX,
            )
        )
        if result.return_code != 0:
            raise RuntimeError("无法读取本机Codex版本。")
        tokens = result.stdout.strip().split()
        if not tokens:
            raise RuntimeError("本机Codex未返回版本。")
        return tokens[-1]

    async def _drain_stderr(
        self,
        reader: AppServerLineReaderPort,
        *,
        instance_id: str,
        process_id: int | None,
        codex_version: str,
    ) -> None:
        """独立排空有界行长 stderr，避免阻塞 App Server。"""

        line_number = 0
        while True:
            line_number += 1
            try:
                line = await reader.readline()
            except AppServerMessageTooLargeError:
                self._log_stderr_diagnostic(
                    code=AgentDiagnosticCode.APP_SERVER_STDERR_TOO_LONG,
                    instance_id=instance_id,
                    process_id=process_id,
                    codex_version=codex_version,
                    line_number=line_number,
                    byte_count=self._max_line_bytes + 1,
                    digest=None,
                )
                continue
            if not line:
                return
            bounded_line = line[: self._max_line_bytes]
            if bounded_line.strip():
                digest = hashlib.sha256(bounded_line).hexdigest()[:16]
                self._log_stderr_diagnostic(
                    code=AgentDiagnosticCode.APP_SERVER_STDERR,
                    instance_id=instance_id,
                    process_id=process_id,
                    codex_version=codex_version,
                    line_number=line_number,
                    byte_count=len(bounded_line),
                    digest=digest,
                )

    def _log_stderr_diagnostic(
        self,
        *,
        code: AgentDiagnosticCode,
        instance_id: str,
        process_id: int | None,
        codex_version: str,
        line_number: int,
        byte_count: int,
        digest: str | None,
    ) -> None:
        """记录一条不包含标准错误原文的结构化诊断。"""

        self._logger.warning(
            AgentDiagnosticEnvelope(
                header=AgentDiagnosticHeader(
                    detail_kind=code,
                    host_id=self._host_id,
                    app_server_instance_id=instance_id,
                    process_id=process_id,
                    codex_version=codex_version,
                    occurred_at=datetime.now(UTC),
                ),
                detail=AgentStderrDiagnosticDetail(
                    kind=cast(
                        Literal[
                            "agent.app_server.stderr",
                            "agent.app_server.stderr_too_long",
                        ],
                        code.value,
                    ),
                    line_number=line_number,
                    byte_count=byte_count,
                    digest=digest,
                ),
            ).to_log_line()
        )

    async def _stop_stderr_task(self) -> None:
        task = self._stderr_task
        self._stderr_task = None
        if task is not None:
            if not task.done():
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=1.0)
                except TimeoutError:
                    task.cancel()
            await asyncio.gather(task, return_exceptions=True)
