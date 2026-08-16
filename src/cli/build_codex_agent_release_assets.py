"""生成 Agent 发布清单、CycloneDX 和 SPDX 制品。"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import shutil
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.core.codex_contract.agent_release_manifest_contract import (
    AGENT_RELEASE_MANIFEST_TARGET_PATH,
    CodexAgentReleaseManifestDetail,
    CodexAgentReleaseManifestEnvelope,
    CodexAgentReleaseManifestHeader,
)
from src.infrastructure.codex_agent.agent_configuration import (
    validate_public_endpoint_url,
)

SPDX_NO_ASSERTION = "NOASSERTION"
AGENT_COMPONENT_NAME = "codex-remote-agent"
AGENT_TARGET_FILE_NAME = "codex-remote-agent.exe"
AGENT_RELEASE_MANIFEST_TARGET_FILE = Path(AGENT_RELEASE_MANIFEST_TARGET_PATH)


class CycloneDxComponent(BaseModel):
    """CycloneDX 软件组件。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["application", "library"]
    name: str
    version: str
    purl: str | None = None


class CycloneDxMetadata(BaseModel):
    """CycloneDX 元数据。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    timestamp: datetime
    component: CycloneDxComponent


class CycloneDxBom(BaseModel):
    """CycloneDX 1.6 JSON 文档。"""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    bom_format: Literal["CycloneDX"] = Field(alias="bomFormat", default="CycloneDX")
    spec_version: Literal["1.6"] = Field(alias="specVersion", default="1.6")
    serial_number: str = Field(alias="serialNumber")
    version: int = 1
    metadata: CycloneDxMetadata
    components: tuple[CycloneDxComponent, ...]


class SpdxCreationInfo(BaseModel):
    """SPDX 创建信息。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    created: datetime
    creators: tuple[str, ...]


class SpdxPackage(BaseModel):
    """SPDX 软件包条目。"""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    name: str
    spdx_id: str = Field(alias="SPDXID")
    version_info: str = Field(alias="versionInfo")
    download_location: str = Field(alias="downloadLocation", default=SPDX_NO_ASSERTION)
    files_analyzed: bool = Field(alias="filesAnalyzed", default=False)


class SpdxDocument(BaseModel):
    """SPDX 2.3 JSON 文档。"""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    spdx_version: Literal["SPDX-2.3"] = Field(alias="spdxVersion", default="SPDX-2.3")
    data_license: Literal["CC0-1.0"] = Field(alias="dataLicense", default="CC0-1.0")
    spdx_id: Literal["SPDXRef-DOCUMENT"] = Field(
        alias="SPDXID",
        default="SPDXRef-DOCUMENT",
    )
    name: str
    document_namespace: str = Field(alias="documentNamespace")
    creation_info: SpdxCreationInfo = Field(alias="creationInfo")
    packages: tuple[SpdxPackage, ...]


class AgentReleaseAssetsCommand(BaseModel):
    """发布制品生成命令。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    executable: Path
    output_directory: Path
    version: str
    minimum_security_version: str
    cdn_base_url: str
    rollout_percent: int = Field(ge=0, le=100)

    @field_validator("cdn_base_url")
    @classmethod
    def validate_cdn_base_url(cls, value: str) -> str:
        """Require a public credential-free HTTPS release origin."""

        return validate_public_endpoint_url(value, expected_scheme="https")


class CodexAgentReleaseAssetsBuilder:
    """构建可审计的发布清单和两种 SBOM。"""

    def build(self, command: AgentReleaseAssetsCommand) -> None:
        """生成发布目标、清单和 SBOM。"""

        if not command.executable.is_file():
            raise FileNotFoundError("Agent可执行文件不存在。")
        published_at = datetime.now(UTC)
        digest_sha256 = hashlib.sha256(command.executable.read_bytes()).hexdigest()
        target_relative_path = Path(
            AGENT_TARGET_FILE_NAME,
            "windows",
            "x86_64",
            "stable",
            command.version,
        )
        target_path = command.output_directory / "targets" / target_relative_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(command.executable, target_path)
        cdn_base_url = command.cdn_base_url.rstrip("/")
        manifest = CodexAgentReleaseManifestEnvelope(
            header=CodexAgentReleaseManifestHeader(),
            detail=CodexAgentReleaseManifestDetail(
                version=command.version,
                digest_sha256=digest_sha256,
                download_url=(
                    f"{cdn_base_url}/targets/{target_relative_path.parent.as_posix()}/"
                    f"{digest_sha256}.{target_relative_path.name}"
                ),
                rollout_percent=command.rollout_percent,
                forced=False,
                minimum_security_version=command.minimum_security_version,
                published_at=published_at,
            ),
        )
        manifest_content = manifest.model_dump_json(indent=2)
        self._write_json(
            command.output_directory / AGENT_RELEASE_MANIFEST_TARGET_FILE,
            manifest_content,
        )
        self._write_json(
            command.output_directory / "targets" / AGENT_RELEASE_MANIFEST_TARGET_FILE,
            manifest_content,
        )
        components = self._read_components(command.version)
        cyclone_dx = CycloneDxBom(
            serialNumber=f"urn:uuid:{uuid4()}",
            metadata=CycloneDxMetadata(
                timestamp=published_at,
                component=components[0],
            ),
            components=components[1:],
        )
        self._write_json(
            command.output_directory / "codex-agent.cdx.json",
            cyclone_dx.model_dump_json(by_alias=True, exclude_none=True, indent=2),
        )
        spdx_packages = tuple(
            SpdxPackage(
                name=component.name,
                SPDXID=f"SPDXRef-Package-{index}",
                versionInfo=component.version,
            )
            for index, component in enumerate(components, start=1)
        )
        spdx = SpdxDocument(
            name=f"{AGENT_COMPONENT_NAME}-{command.version}",
            documentNamespace=f"{cdn_base_url}/spdx/{uuid4()}",
            creationInfo=SpdxCreationInfo(
                created=published_at,
                creators=("Tool: CodexAgentReleaseAssetsBuilder",),
            ),
            packages=spdx_packages,
        )
        self._write_json(
            command.output_directory / "codex-agent.spdx.json",
            spdx.model_dump_json(by_alias=True, indent=2),
        )

    def _read_components(self, agent_version: str) -> tuple[CycloneDxComponent, ...]:
        dependencies = tuple(
            CycloneDxComponent(
                type="library",
                name=distribution.metadata["Name"],
                version=distribution.version,
                purl=(f"pkg:pypi/{distribution.metadata['Name'].lower()}@{distribution.version}"),
            )
            for distribution in sorted(
                importlib.metadata.distributions(),
                key=lambda item: item.metadata["Name"].lower(),
            )
            if distribution.metadata["Name"]
        )
        return (
            CycloneDxComponent(
                type="application",
                name=AGENT_COMPONENT_NAME,
                version=agent_version,
            ),
            *dependencies,
        )

    def _write_json(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_suffix(f"{path.suffix}.tmp")
        temporary_path.write_text(f"{content}\n", encoding="utf-8")
        temporary_path.replace(path)


class CodexAgentReleaseAssetsCli:
    """发布制品生成命令行入口。"""

    def execute(self, argv: Sequence[str] | None = None) -> int:
        """解析参数并生成发布制品。"""

        parser = argparse.ArgumentParser(description="生成 Codex Remote Agent 发布制品")
        parser.add_argument("--executable", required=True, type=Path)
        parser.add_argument("--output-directory", required=True, type=Path)
        parser.add_argument("--version", required=True)
        parser.add_argument("--minimum-security-version", required=True)
        parser.add_argument("--cdn-base-url", required=True)
        parser.add_argument("--rollout-percent", required=True, type=int)
        arguments = parser.parse_args(argv)
        command = AgentReleaseAssetsCommand(
            executable=arguments.executable,
            output_directory=arguments.output_directory,
            version=arguments.version,
            minimum_security_version=arguments.minimum_security_version,
            cdn_base_url=arguments.cdn_base_url,
            rollout_percent=arguments.rollout_percent,
        )
        CodexAgentReleaseAssetsBuilder().build(command)
        logger.info("Agent发布制品已生成：{}", command.output_directory)
        return 0


if __name__ == "__main__":
    raise SystemExit(CodexAgentReleaseAssetsCli().execute())
