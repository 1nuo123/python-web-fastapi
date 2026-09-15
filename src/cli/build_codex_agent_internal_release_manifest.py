"""生成不含 TUF 与自动更新能力的 Windows Agent 内部体验清单。"""

from __future__ import annotations

import argparse
import hashlib
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.core.codex_contract.agent_release_manifest_contract import (
    CodexAgentInternalReleaseManifestDetail,
    CodexAgentInternalReleaseManifestEnvelope,
    CodexAgentInternalReleaseManifestHeader,
    parse_agent_release_version,
)


class AgentInternalReleaseManifestBuildCommand(BaseModel):
    """内部体验 MSI 清单的显式构建输入。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    installer: Path
    output: Path
    version: str = Field(min_length=1, max_length=64)
    download_url: str = Field(min_length=1, max_length=2_048)
    source_repository: str | None = Field(default=None, max_length=256)
    source_revision: str | None = Field(default=None, max_length=128)
    source_dirty: bool | None = None

    @field_validator("version")
    @classmethod
    def validate_release_version(cls, value: str) -> str:
        """内部 MSI 也必须使用 Windows Installer 支持的三段版本。"""

        parse_agent_release_version(value)
        return value


class CodexAgentInternalReleaseManifestBuilder:
    """把已构建 MSI 转换为用户可核验的内部体验发布清单。"""

    def build(
        self,
        command: AgentInternalReleaseManifestBuildCommand,
    ) -> CodexAgentInternalReleaseManifestEnvelope:
        """原子写入与 MSI 内容绑定的清单。

        该方法只读取公开 MSI 字节并输出 SHA-256；不会写入部署密钥、令牌或
        Agent 设备私钥。URL 与自动更新边界由强类型契约在写入前校验。
        """

        if not command.installer.is_file():
            raise FileNotFoundError("内部体验 MSI 不存在。")
        manifest = CodexAgentInternalReleaseManifestEnvelope(
            header=CodexAgentInternalReleaseManifestHeader(),
            detail=CodexAgentInternalReleaseManifestDetail(
                version=command.version,
                artifact_sha256=hashlib.sha256(command.installer.read_bytes()).hexdigest(),
                download_url=command.download_url,
                published_at=datetime.now(UTC),
                source_repository=command.source_repository,
                source_revision=command.source_revision,
                source_dirty=command.source_dirty,
            ),
        )
        command.output.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = command.output.with_suffix(f"{command.output.suffix}.tmp")
        temporary_path.write_text(
            f"{manifest.model_dump_json(indent=2)}\n",
            encoding="utf-8",
        )
        temporary_path.replace(command.output)
        return manifest


class CodexAgentInternalReleaseManifestCli:
    """内部体验发布清单命令行入口。"""

    def execute(self, argv: Sequence[str] | None = None) -> int:
        """解析可审计输入并生成单个内部体验清单。"""

        parser = argparse.ArgumentParser(description="生成 Codex Agent 内部体验发布清单")
        parser.add_argument("--installer", required=True, type=Path)
        parser.add_argument("--output", required=True, type=Path)
        parser.add_argument("--version", required=True)
        parser.add_argument("--download-url", required=True)
        parser.add_argument("--source-repository")
        parser.add_argument("--source-revision")
        parser.add_argument("--source-dirty", action="store_true")
        arguments = parser.parse_args(argv)
        command = AgentInternalReleaseManifestBuildCommand(
            installer=arguments.installer,
            output=arguments.output,
            version=arguments.version,
            download_url=arguments.download_url,
            source_repository=arguments.source_repository,
            source_revision=arguments.source_revision,
            source_dirty=True if arguments.source_dirty else None,
        )
        CodexAgentInternalReleaseManifestBuilder().build(command)
        logger.info("Agent内部体验发布清单已生成：{}", command.output)
        return 0


if __name__ == "__main__":
    raise SystemExit(CodexAgentInternalReleaseManifestCli().execute())
