"""生成 PyInstaller 使用的 Windows Agent 版本资源。"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, field_validator


class WindowsVersionInfoBuildCommand(BaseModel):
    """Windows 文件版本资源生成命令。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    output: Path

    @field_validator("version")
    @classmethod
    def validate_version_components(cls, value: str) -> str:
        """Windows 文件版本的四段值均限制为 uint16。"""

        if any(int(part) > 65_535 for part in value.split(".")):
            raise ValueError("Windows文件版本分段不得超过65535。")
        return value


class CodexAgentWindowsVersionInfoBuilder:
    """生成稳定的 VSVersionInfo 文本资源。"""

    def build(self, command: WindowsVersionInfoBuildCommand) -> None:
        """原子写入 PyInstaller 版本资源。"""

        major, minor, patch = (int(part) for part in command.version.split("."))
        version_tuple = f"({major}, {minor}, {patch}, 0)"
        content = f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={version_tuple},
    prodvers={version_tuple},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0),
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '080404b0',
        [
          StringStruct('CompanyName', 'Codex Remote'),
          StringStruct('FileDescription', 'Codex Remote Agent'),
          StringStruct('FileVersion', '{command.version}.0'),
          StringStruct('InternalName', 'codex-remote-agent'),
          StringStruct('OriginalFilename', 'codex-remote-agent.exe'),
          StringStruct('ProductName', 'Codex Remote Agent'),
          StringStruct('ProductVersion', '{command.version}.0'),
        ],
      ),
    ]),
    VarFileInfo([VarStruct('Translation', [2052, 1200])]),
  ],
)
"""
        command.output.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = command.output.with_suffix(f"{command.output.suffix}.tmp")
        temporary_path.write_text(content, "utf-8")
        temporary_path.replace(command.output)


class CodexAgentWindowsVersionInfoCli:
    """Windows 文件版本资源命令行入口。"""

    def execute(self, argv: Sequence[str] | None = None) -> int:
        """解析版本与输出路径后生成资源。"""

        parser = argparse.ArgumentParser(description="生成 Codex Remote Agent Windows版本资源")
        parser.add_argument("--version", required=True)
        parser.add_argument("--output", required=True, type=Path)
        arguments = parser.parse_args(argv)
        command = WindowsVersionInfoBuildCommand(
            version=arguments.version,
            output=arguments.output,
        )
        CodexAgentWindowsVersionInfoBuilder().build(command)
        logger.info("Agent Windows版本资源已生成：{}", command.output)
        return 0


if __name__ == "__main__":
    raise SystemExit(CodexAgentWindowsVersionInfoCli().execute())
