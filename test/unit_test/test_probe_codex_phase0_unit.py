"""Phase 0 Codex探针运行环境单元测试。"""

from __future__ import annotations

import subprocess

from pytest import MonkeyPatch

from src.cli.probe_codex_phase0 import CodexPhase0Probe
from src.infrastructure.codex_agent.app_server_process_supervisor import CodexProcessSupport


class TestProbeCodexPhase0Unit:
    """独立Codex子进程环境测试。"""

    def test_environment_should_remove_parent_codex_markers_but_keep_user_home(
        self,
        monkeypatch: MonkeyPatch,
    ) -> None:
        """验证桌面父进程不会把探针重定向到内置旧CLI。"""

        monkeypatch.setenv("CODEX_INTERNAL_ORIGINATOR_OVERRIDE", "Codex Desktop")
        monkeypatch.setenv("CODEX_THREAD_ID", "thread-parent")
        monkeypatch.setenv("CODEX_HOME", "C:/Users/test/.codex")

        environment = CodexProcessSupport.build_standalone_environment()

        assert "CODEX_INTERNAL_ORIGINATOR_OVERRIDE" not in environment
        assert "CODEX_THREAD_ID" not in environment
        assert environment["CODEX_HOME"] == "C:/Users/test/.codex"

    def test_read_version_should_execute_resolved_codex_command(
        self,
        monkeypatch: MonkeyPatch,
    ) -> None:
        """验证Windows npm入口解析结果不会退回同名旧codex.exe。"""

        captured_command: list[str] = []

        def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            captured_command.extend(command)
            return subprocess.CompletedProcess(
                args=command,
                returncode=0,
                stdout="codex-cli 0.145.0\n",
            )

        monkeypatch.setattr(subprocess, "run", fake_run)

        version = CodexPhase0Probe()._read_codex_version(  # noqa: SLF001
            ("C:/Node/node.exe", "C:/npm/codex.js")
        )

        assert version == "codex-cli 0.145.0"
        assert captured_command == [
            "C:/Node/node.exe",
            "C:/npm/codex.js",
            "--version",
        ]
