"""Windows 无窗口子进程启动器单元测试。"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys

import pytest
from pydantic import ValidationError

from src.infrastructure.process.windows_subprocess_launcher import (
    WindowsSubprocessLauncher,
    WindowsSubprocessPolicy,
    WindowsSubprocessRequest,
)

SUBPROCESS_TEST_TIMEOUT_SECONDS = 5.0
SUBPROCESS_CANCEL_WAIT_SECONDS = 30


class TestWindowsSubprocessLauncherUnit:
    """覆盖同步、异步、超时、取消与强类型请求。"""

    def test_sync_process_should_capture_output_and_apply_hidden_policy(self) -> None:
        policy = WindowsSubprocessPolicy.current()
        result = WindowsSubprocessLauncher(policy).run(
            WindowsSubprocessRequest(
                argv=(
                    sys.executable,
                    "-c",
                    "import sys;sys.stdout.write('ok');sys.stderr.write('warn')",
                ),
                timeout_seconds=SUBPROCESS_TEST_TIMEOUT_SECONDS,
            )
        )

        assert result.return_code == 0
        assert result.stdout == "ok"
        assert result.stderr == "warn"
        assert policy.shell is False
        if os.name == "nt":
            assert policy.creation_flags & subprocess.CREATE_NO_WINDOW

    def test_sync_process_should_allow_following_complete_lifecycle(self) -> None:
        result = WindowsSubprocessLauncher().run(
            WindowsSubprocessRequest(
                argv=(sys.executable, "-c", "raise SystemExit(0)"),
                timeout_seconds=None,
            )
        )

        assert result.return_code == 0

    @pytest.mark.asyncio
    async def test_async_process_should_capture_output(self) -> None:
        result = await WindowsSubprocessLauncher().run_async(
            WindowsSubprocessRequest(
                argv=(sys.executable, "-c", "import sys;sys.stdout.write('async-ok')"),
                timeout_seconds=SUBPROCESS_TEST_TIMEOUT_SECONDS,
            )
        )

        assert result.return_code == 0
        assert result.stdout == "async-ok"

    @pytest.mark.asyncio
    async def test_async_process_should_cleanup_on_cancellation(self) -> None:
        task = asyncio.create_task(
            WindowsSubprocessLauncher().run_async(
                WindowsSubprocessRequest(
                    argv=(
                        sys.executable,
                        "-c",
                        f"import time;time.sleep({SUBPROCESS_CANCEL_WAIT_SECONDS})",
                    ),
                    timeout_seconds=SUBPROCESS_CANCEL_WAIT_SECONDS,
                )
            )
        )
        await asyncio.sleep(0.1)
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

    def test_request_should_forbid_arbitrary_extension_fields(self) -> None:
        with pytest.raises(ValidationError, match="extra_forbidden"):
            WindowsSubprocessRequest.model_validate(
                {
                    "argv": [sys.executable, "--version"],
                    "metadata": {"secret": "forbidden"},
                }
            )

    def test_policy_should_reject_shell_execution(self) -> None:
        with pytest.raises(ValidationError, match="literal_error"):
            WindowsSubprocessPolicy.model_validate({"shell": True})
