"""生成可复现的 Windows Agent MSI 产品身份。"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
from typing import Final, Literal
from uuid import UUID, uuid5

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, field_validator

WINDOWS_INSTALLER_UPGRADE_CODE: Final = UUID("8a0a4d2e-ed6e-4c7d-bf9a-5f03c80a15e6")
WINDOWS_INSTALLER_PRODUCT_NAMESPACE: Final = UUID("9e36b7c5-fde8-55ec-b52a-87a85acd6ef7")
WINDOWS_INSTALLER_ARCHITECTURE: Final = "x64"
WINDOWS_INSTALLER_PLATFORM: Final = "windows-x86_64"


class WindowsInstallerIdentityBuildCommand(BaseModel):
    """MSI 产品身份生成命令。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    output: Path

    @field_validator("version")
    @classmethod
    def validate_windows_installer_version(cls, value: str) -> str:
        """限制到 Windows Installer 支持的三段版本范围。"""

        major, minor, build = (int(part) for part in value.split("."))
        if major > 255 or minor > 255 or build > 65_535:
            raise ValueError("MSI版本超出Windows Installer允许范围。")
        return value


class WindowsInstallerIdentity(BaseModel):
    """可审计、可复现的 MSI 产品身份。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str
    product_code: str
    upgrade_code: str
    architecture: Literal["x64"] = "x64"


class CodexAgentWindowsInstallerIdentityBuilder:
    """按版本和平台生成稳定 ProductCode。"""

    def build(
        self,
        command: WindowsInstallerIdentityBuildCommand,
    ) -> WindowsInstallerIdentity:
        """生成身份并原子写入 JSON。"""

        product_code = uuid5(
            WINDOWS_INSTALLER_PRODUCT_NAMESPACE,
            f"codex-remote-agent:{WINDOWS_INSTALLER_PLATFORM}:{command.version}",
        )
        identity = WindowsInstallerIdentity(
            version=command.version,
            product_code=self._format_guid(product_code),
            upgrade_code=self._format_guid(WINDOWS_INSTALLER_UPGRADE_CODE),
        )
        command.output.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = command.output.with_suffix(f"{command.output.suffix}.tmp")
        temporary_path.write_text(
            f"{identity.model_dump_json(indent=2)}\n",
            encoding="utf-8",
        )
        temporary_path.replace(command.output)
        return identity

    @staticmethod
    def _format_guid(value: UUID) -> str:
        return f"{{{str(value).upper()}}}"


class CodexAgentWindowsInstallerIdentityCli:
    """MSI 产品身份生成命令行入口。"""

    def execute(self, argv: Sequence[str] | None = None) -> int:
        """解析参数并生成身份文件。"""

        parser = argparse.ArgumentParser(description="生成 Codex Remote Agent MSI 身份")
        parser.add_argument("--version", required=True)
        parser.add_argument("--output", required=True, type=Path)
        arguments = parser.parse_args(argv)
        command = WindowsInstallerIdentityBuildCommand(
            version=arguments.version,
            output=arguments.output,
        )
        CodexAgentWindowsInstallerIdentityBuilder().build(command)
        logger.info("Agent MSI产品身份已生成：{}", command.output)
        return 0


if __name__ == "__main__":
    raise SystemExit(CodexAgentWindowsInstallerIdentityCli().execute())
