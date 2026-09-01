"""App Server 子进程监督器单元测试。"""

from __future__ import annotations

import asyncio
import logging
import sys
from collections.abc import Awaitable
from pathlib import Path

import pytest
from pydantic import JsonValue

from src.core.codex_contract.app_server_jsonrpc_contract import (
    AppServerMessageTooLargeError,
    JsonRpcId,
)
from src.infrastructure.codex_agent.app_server_process_supervisor import (
    CODEX_PARENT_PROCESS_VARIABLES,
    AppServerProcessSupervisor,
    CodexProcessSupport,
)

FROZEN_CODEX_VERSION = "0.145.0"
MAX_LINE_BYTES = 4_096


class SequenceLineReader:
    """按顺序返回异常、数据行和 EOF。"""

    def __init__(self) -> None:
        self._index = 0

    async def readline(self) -> bytes:
        self._index += 1
        if self._index == 1:
            raise AppServerMessageTooLargeError(MAX_LINE_BYTES)
        if self._index == 2:
            return b"sensitive stderr\n"
        return b""


class RecordingTransport:
    """记录 Windows transport close。"""

    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class ProcessWithTransport:
    """提供监督器内部 transport 字段。"""

    def __init__(self, transport: RecordingTransport) -> None:
        self._transport = transport


class TestAppServerProcessSupervisorUnit:
    """覆盖真实假子进程启动、重启、停止和入口解析。"""

    @pytest.mark.asyncio
    async def test_supervisor_should_start_initialize_restart_and_stop_real_fixture(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fixture = Path("test/fixtures/fake_codex_app_server.py").resolve()
        monkeypatch.setattr(
            CodexProcessSupport,
            "resolve_command",
            lambda _binary: (sys.executable, str(fixture)),
        )

        async def ignore_notification(_method: str, _params: JsonValue) -> None:
            return None

        async def reject_request(
            _request_id: JsonRpcId,
            _method: str,
            _params: JsonValue,
        ) -> None:
            raise AssertionError("本场景不应收到 App Server 主动请求。")

        async def ignore_warning(_warning: str) -> None:
            return None

        supervisor = AppServerProcessSupervisor(
            codex_binary="fake-codex",
            allowed_versions=[FROZEN_CODEX_VERSION],
            max_line_bytes=MAX_LINE_BYTES,
            notification_handler=ignore_notification,
            request_handler=reject_request,
            warning_handler=ignore_warning,
            logger=logging.getLogger("test.app-server-supervisor"),
        )
        with pytest.raises(RuntimeError, match="尚未启动"):
            _ = supervisor.handle
        try:
            first = await supervisor.start()
            assert first.codex_version == FROZEN_CODEX_VERSION
            assert isinstance(first.initialize_result, dict)
            assert first.initialize_result["platformOs"] == "windows"
            with pytest.raises(RuntimeError, match="重复启动"):
                await supervisor.start()

            second = await supervisor.restart()
            assert second.instance_id != first.instance_id
            assert second.client.running is True
        finally:
            await supervisor.stop()
            await supervisor.stop()

    @pytest.mark.asyncio
    async def test_supervisor_should_start_version_outside_legacy_allowlist(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fixture = Path("test/fixtures/fake_codex_app_server.py").resolve()
        monkeypatch.setattr(
            CodexProcessSupport,
            "resolve_command",
            lambda _binary: (sys.executable, str(fixture)),
        )

        async def ignore_notification(_method: str, _params: JsonValue) -> None:
            return None

        async def reject_request(
            _request_id: JsonRpcId,
            _method: str,
            _params: JsonValue,
        ) -> None:
            return None

        async def ignore_warning(_warning: str) -> None:
            return None

        supervisor = AppServerProcessSupervisor(
            codex_binary="fake-codex",
            allowed_versions=["9.*"],
            max_line_bytes=MAX_LINE_BYTES,
            notification_handler=ignore_notification,
            request_handler=reject_request,
            warning_handler=ignore_warning,
            logger=logging.getLogger("test.app-server-supervisor"),
        )

        handle = await supervisor.start()
        assert handle.codex_version == FROZEN_CODEX_VERSION
        await supervisor.stop()

    def test_process_support_should_strip_parent_environment_and_resolve_entries(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import src.infrastructure.codex_agent.app_server_process_supervisor as module

        for variable_name in CODEX_PARENT_PROCESS_VARIABLES:
            monkeypatch.setenv(variable_name, "sensitive")
        environment = CodexProcessSupport.build_standalone_environment()
        assert CODEX_PARENT_PROCESS_VARIABLES.isdisjoint(environment)

        executable = tmp_path / "codex.exe"
        executable.write_bytes(b"binary")
        monkeypatch.setattr(module.shutil, "which", lambda value: str(executable))
        assert CodexProcessSupport.resolve_command("codex") == (str(executable),)

        command = tmp_path / "codex.cmd"
        command.write_text("@echo off", encoding="ascii")
        npm_entry = tmp_path / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
        npm_entry.parent.mkdir(parents=True)
        npm_entry.write_text("", encoding="ascii")

        def resolve_with_node(value: str) -> str | None:
            if value == "codex":
                return str(command)
            if value == "node":
                return str(tmp_path / "node.exe")
            return None

        monkeypatch.setattr(module.shutil, "which", resolve_with_node)
        assert CodexProcessSupport.resolve_command("codex") == (
            str(tmp_path / "node.exe"),
            str(npm_entry),
        )

        def resolve_without_node(value: str) -> str | None:
            return str(command) if value == "codex" else None

        monkeypatch.setattr(module.shutil, "which", resolve_without_node)
        with pytest.raises(FileNotFoundError, match="Node.js"):
            CodexProcessSupport.resolve_command("codex")
        monkeypatch.setattr(module.shutil, "which", lambda _value: None)
        with pytest.raises(FileNotFoundError, match="Codex"):
            CodexProcessSupport.resolve_command("missing")

    @pytest.mark.asyncio
    async def test_stderr_drain_should_redact_content_and_continue_after_oversize(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.setattr(CodexProcessSupport, "resolve_command", lambda _binary: ("fake",))

        async def ignore_notification(_method: str, _params: JsonValue) -> None:
            return None

        async def reject_request(
            _request_id: JsonRpcId,
            _method: str,
            _params: JsonValue,
        ) -> None:
            return None

        async def ignore_warning(_warning: str) -> None:
            return None

        logger = logging.getLogger("test.app-server-stderr")
        supervisor = AppServerProcessSupervisor(
            codex_binary="fake",
            allowed_versions=[FROZEN_CODEX_VERSION],
            max_line_bytes=MAX_LINE_BYTES,
            notification_handler=ignore_notification,
            request_handler=reject_request,
            warning_handler=ignore_warning,
            logger=logger,
        )
        with caplog.at_level(logging.WARNING, logger=logger.name):
            await supervisor._drain_stderr(  # noqa: SLF001
                SequenceLineReader(),
                instance_id="instance-stderr",
                process_id=1234,
                codex_version=FROZEN_CODEX_VERSION,
            )

        messages = [record.getMessage() for record in caplog.records]
        assert any("agent.app_server.stderr_too_long" in message for message in messages)
        assert any("digest=" in message for message in messages)
        assert any("host_id=unbound" in message for message in messages)
        assert any("App_Server代次=instance-stderr" in message for message in messages)
        assert any("PID=1234" in message for message in messages)
        assert all("sensitive stderr" not in message for message in messages)

    def test_windows_transport_close_should_delegate_only_on_windows(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import src.infrastructure.codex_agent.app_server_process_supervisor as module

        transport = RecordingTransport()
        process = ProcessWithTransport(transport)
        monkeypatch.setattr(module.os, "name", "posix")
        CodexProcessSupport.close_windows_subprocess_transport(process)  # type: ignore[arg-type]
        assert transport.closed is False
        monkeypatch.setattr(module.os, "name", "nt")
        CodexProcessSupport.close_windows_subprocess_transport(process)  # type: ignore[arg-type]
        assert transport.closed is True

    @pytest.mark.asyncio
    async def test_stop_stderr_task_should_cancel_reader_after_timeout(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(CodexProcessSupport, "resolve_command", lambda _binary: ("fake",))

        async def ignore_notification(_method: str, _params: JsonValue) -> None:
            return None

        async def reject_request(
            _request_id: JsonRpcId,
            _method: str,
            _params: JsonValue,
        ) -> None:
            return None

        async def ignore_warning(_warning: str) -> None:
            return None

        supervisor = AppServerProcessSupervisor(
            codex_binary="fake",
            allowed_versions=[FROZEN_CODEX_VERSION],
            max_line_bytes=MAX_LINE_BYTES,
            notification_handler=ignore_notification,
            request_handler=reject_request,
            warning_handler=ignore_warning,
            logger=logging.getLogger("test.app-server-timeout"),
        )
        blocker = asyncio.Event()
        supervisor._stderr_task = asyncio.create_task(  # noqa: SLF001
            self._wait_for_event(blocker)
        )
        original_wait_for = asyncio.wait_for

        async def immediate_timeout(
            awaitable: Awaitable[object],
            *,
            timeout: float | None,
        ) -> object:
            if timeout == 1.0:
                raise TimeoutError
            return await original_wait_for(awaitable, timeout=timeout)

        monkeypatch.setattr(asyncio, "wait_for", immediate_timeout)
        await supervisor._stop_stderr_task()  # noqa: SLF001
        assert supervisor._stderr_task is None  # noqa: SLF001

    @staticmethod
    async def _wait_for_event(event: asyncio.Event) -> None:
        await event.wait()
