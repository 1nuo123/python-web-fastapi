"""生成本机 App Server schema 并执行 Phase 0 审批协议探针。"""

from __future__ import annotations

import argparse
import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

from src.infrastructure.codex_agent.app_server_approval_protocol_probe import (
    AppServerApprovalProtocolProbe,
)
from src.infrastructure.codex_agent.app_server_process_supervisor import CodexProcessSupport

DEFAULT_CODEX_EXECUTABLE: Final = "codex"


class CodexPhase0ProbeCommand(BaseModel):
    """Phase 0 探针强类型输入。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    codex_binary: str = Field(min_length=1)
    schema_directory: Path | None = None


class CodexPhase0Probe:
    """生成或读取 schema 并返回脱敏探针 JSON。"""

    def execute(self, command: CodexPhase0ProbeCommand) -> str:
        codex_command = CodexProcessSupport.resolve_command(command.codex_binary)
        version = self._read_codex_version(codex_command)
        if command.schema_directory is not None:
            result = AppServerApprovalProtocolProbe().run(
                schema_directory=command.schema_directory,
                codex_version=version,
            )
            return result.model_dump_json(indent=2)
        with tempfile.TemporaryDirectory(prefix="codex-phase0-schema-") as temporary_directory:
            generated_directory = Path(temporary_directory)
            subprocess.run(
                [
                    *codex_command,
                    "app-server",
                    "generate-json-schema",
                    "--out",
                    str(generated_directory),
                ],
                check=True,
                capture_output=True,
                text=True,
                env=CodexProcessSupport.build_standalone_environment(),
            )
            result = AppServerApprovalProtocolProbe().run(
                schema_directory=generated_directory,
                codex_version=version,
            )
            return result.model_dump_json(indent=2)

    def _read_codex_version(self, codex_command: tuple[str, ...]) -> str:
        completed = subprocess.run(
            [*codex_command, "--version"],
            check=True,
            capture_output=True,
            text=True,
            env=CodexProcessSupport.build_standalone_environment(),
        )
        version = completed.stdout.strip()
        if not version:
            raise RuntimeError("Codex CLI未返回版本。")
        return version


class CodexPhase0ProbeCli:
    """Phase 0 探针命令行入口。"""

    def build_argument_parser(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(description="验证本机Codex App Server审批协议")
        parser.add_argument("--codex-bin", default=DEFAULT_CODEX_EXECUTABLE)
        parser.add_argument("--schema-dir", type=Path)
        return parser

    def execute(self, argv: Sequence[str] | None = None) -> int:
        arguments = self.build_argument_parser().parse_args(argv)
        result = CodexPhase0Probe().execute(
            CodexPhase0ProbeCommand(
                codex_binary=str(arguments.codex_bin),
                schema_directory=arguments.schema_dir,
            )
        )
        logger.info("Phase 0审批协议探针结果：\n{}", result)
        return 0


if __name__ == "__main__":
    raise SystemExit(CodexPhase0ProbeCli().execute())
