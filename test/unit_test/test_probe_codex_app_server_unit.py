"""App Server 探针 manifest 解析与版本约束测试。"""

from __future__ import annotations

from pathlib import Path

from src.cli.probe_codex_app_server import CodexAppServerCompatibilityProbe

MANIFEST_PATH = Path("protocol/codex_app_server/0.145.0/manifest.json")
WORKSPACE_PATH = Path(".")


class TestProbeCodexAppServerUnit:
    """验证探针读取公共头与强类型扩展字段。"""

    def test_nested_manifest_should_use_header_version_and_detail_digest(self) -> None:
        probe = CodexAppServerCompatibilityProbe(
            codex_binary="codex",
            workspace=WORKSPACE_PATH,
            manifest_path=MANIFEST_PATH,
            run_turn=False,
        )

        assert probe._read_manifest_version() == "0.145.0"  # noqa: SLF001
