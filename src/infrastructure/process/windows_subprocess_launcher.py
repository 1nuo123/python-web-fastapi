"""通用 Windows 子进程统一启动策略。"""

from __future__ import annotations

import asyncio
import os
import subprocess
import time
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Final, Literal, cast
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

WINDOWS_SUBPROCESS_DEFAULT_TIMEOUT_SECONDS: Final = 60.0
WINDOWS_SUBPROCESS_OUTPUT_ENCODING: Final = "utf-8"
WINDOWS_SUBPROCESS_OUTPUT_ERROR_POLICY: Final = "replace"
WINDOWS_SUBPROCESS_DEFAULT_STREAM_LIMIT_BYTES: Final = 65_536
WINDOWS_SUBPROCESS_SCHEMA_VERSION: Final = "1.0"


class WindowsCommandProcessExtension(BaseModel):
    """普通 Windows CLI 进程扩展。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["windows_command_process"] = "windows_command_process"
    schema_version: Literal["1.0"] = WINDOWS_SUBPROCESS_SCHEMA_VERSION


class WindowsAppServerProcessExtension(BaseModel):
    """Codex App Server 长驻进程扩展。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["windows_app_server_process"] = "windows_app_server_process"
    schema_version: Literal["1.0"] = WINDOWS_SUBPROCESS_SCHEMA_VERSION
    start_suspended: bool = False


WindowsProcessExtension = Annotated[
    WindowsCommandProcessExtension | WindowsAppServerProcessExtension,
    Field(discriminator="kind"),
]


class WindowsSubprocessLogCategory(StrEnum):
    """子进程日志分类。"""

    CODEX = "codex"
    GIT = "git"
    NODE = "node"
    POWERSHELL = "powershell"
    WINDOWS = "windows"
    OTHER = "other"


class WindowsSubprocessRequest(BaseModel):
    """统一子进程请求参数。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["windows_subprocess_request"] = "windows_subprocess_request"
    schema_version: Literal["1.0"] = WINDOWS_SUBPROCESS_SCHEMA_VERSION
    argv: tuple[str, ...] = Field(min_length=1)
    cwd: Path | None = None
    environment: dict[str, str] | None = None
    timeout_seconds: float | None = Field(
        default=WINDOWS_SUBPROCESS_DEFAULT_TIMEOUT_SECONDS,
        gt=0,
    )
    stream_limit_bytes: int = Field(
        default=WINDOWS_SUBPROCESS_DEFAULT_STREAM_LIMIT_BYTES,
        gt=0,
    )
    input_text: str | None = None
    log_category: WindowsSubprocessLogCategory = WindowsSubprocessLogCategory.OTHER
    extension: WindowsProcessExtension = Field(default_factory=WindowsCommandProcessExtension)

    @model_validator(mode="after")
    def validate_extension_version(self) -> WindowsSubprocessRequest:
        """确保请求与进程扩展使用同一契约版本。"""

        if self.extension.schema_version != self.schema_version:
            raise ValueError("Windows子进程请求与扩展版本不一致。")
        return self


class WindowsSubprocessPolicy(BaseModel):
    """不继承可见控制台的固定启动策略。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    shell: Literal[False] = False
    creation_flags: int = 0

    @classmethod
    def current(cls) -> WindowsSubprocessPolicy:
        """构造当前平台的无窗口策略。"""

        return cls(
            creation_flags=(getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0)
        )

    def startup_info(self) -> subprocess.STARTUPINFO | None:
        """在 Windows 上隐藏子进程窗口。"""

        startup_info_type = getattr(subprocess, "STARTUPINFO", None)
        if startup_info_type is None:
            return None
        startup_info = startup_info_type()
        startup_info.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
        startup_info.wShowWindow = getattr(subprocess, "SW_HIDE", 0)
        return cast(subprocess.STARTUPINFO, startup_info)


class WindowsSubprocessResult(BaseModel):
    """子进程退出结果，不暴露任意字典。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    return_code: int
    stdout: str
    stderr: str
    elapsed_seconds: float = Field(ge=0)
    log_id: str = Field(min_length=1, max_length=64)


class WindowsSubprocessLauncher:
    """提供同步和异步的无窗口子进程调用。"""

    def __init__(self, policy: WindowsSubprocessPolicy | None = None) -> None:
        self._policy = policy or WindowsSubprocessPolicy.current()

    def run(self, request: WindowsSubprocessRequest) -> WindowsSubprocessResult:
        """执行同步子进程并收集 stdout/stderr；空超时表示跟随进程完整生命周期。"""

        started_at = time.monotonic()
        completed = subprocess.run(
            list(request.argv),
            check=False,
            cwd=str(request.cwd) if request.cwd is not None else None,
            env=(dict(request.environment) if request.environment is not None else None),
            input=request.input_text,
            capture_output=True,
            text=True,
            encoding=WINDOWS_SUBPROCESS_OUTPUT_ENCODING,
            errors=WINDOWS_SUBPROCESS_OUTPUT_ERROR_POLICY,
            timeout=request.timeout_seconds,
            shell=False,
            startupinfo=self._policy.startup_info(),
            creationflags=self._policy.creation_flags,
        )
        return WindowsSubprocessResult(
            return_code=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
            elapsed_seconds=max(time.monotonic() - started_at, 0.0),
            log_id=str(uuid4()),
        )

    async def create_async(
        self,
        request: WindowsSubprocessRequest,
        *,
        stdin: int | None = None,
        stdout: int | None = asyncio.subprocess.PIPE,
        stderr: int | None = asyncio.subprocess.PIPE,
    ) -> asyncio.subprocess.Process:
        """创建异步子进程，沿用同一无窗口参数。"""

        creation_flags = self._policy.creation_flags
        if (
            os.name == "nt"
            and isinstance(request.extension, WindowsAppServerProcessExtension)
            and request.extension.start_suspended
        ):
            creation_flags |= 0x00000004  # CREATE_SUSPENDED: 先绑定 Job，再运行任何子进程代码。
        return await asyncio.create_subprocess_exec(
            *request.argv,
            cwd=str(request.cwd) if request.cwd is not None else None,
            env=(dict(request.environment) if request.environment is not None else None),
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            startupinfo=self._policy.startup_info(),
            creationflags=creation_flags,
            limit=request.stream_limit_bytes,
        )

    async def run_async(self, request: WindowsSubprocessRequest) -> WindowsSubprocessResult:
        """执行异步子进程，支持可选超时和取消时清理。"""

        started_at = time.monotonic()
        process = await self.create_async(request, stdin=asyncio.subprocess.PIPE)
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(
                    request.input_text.encode(WINDOWS_SUBPROCESS_OUTPUT_ENCODING)
                    if request.input_text is not None
                    else None
                ),
                timeout=request.timeout_seconds,
            )
        except (TimeoutError, asyncio.CancelledError):
            if process.returncode is None:
                process.kill()
                await process.wait()
            raise
        return WindowsSubprocessResult(
            return_code=process.returncode if process.returncode is not None else -1,
            stdout=stdout.decode(
                WINDOWS_SUBPROCESS_OUTPUT_ENCODING, errors=WINDOWS_SUBPROCESS_OUTPUT_ERROR_POLICY
            )
            if isinstance(stdout, bytes)
            else str(stdout or ""),
            stderr=stderr.decode(
                WINDOWS_SUBPROCESS_OUTPUT_ENCODING, errors=WINDOWS_SUBPROCESS_OUTPUT_ERROR_POLICY
            )
            if isinstance(stderr, bytes)
            else str(stderr or ""),
            elapsed_seconds=max(time.monotonic() - started_at, 0.0),
            log_id=str(uuid4()),
        )
