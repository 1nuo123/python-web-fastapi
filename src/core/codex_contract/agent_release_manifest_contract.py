"""Codex Remote Agent 发布清单公共契约。"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

AGENT_RELEASE_MANIFEST_KIND: Final = "codex_agent_release_manifest"
AGENT_RELEASE_MANIFEST_SCHEMA_VERSION: Final = "1.0"
AGENT_RELEASE_MANIFEST_TARGET_PATH: Final = "codex-agent-release.json"
SHA256_HEX_LENGTH: Final = 64
AGENT_RELEASE_VERSION_PATTERN: Final = re.compile(r"^\d+\.\d+\.\d+$")


def parse_agent_release_version(value: str) -> tuple[int, int, int]:
    """Parse the canonical three-part Agent release version."""

    if AGENT_RELEASE_VERSION_PATTERN.fullmatch(value) is None:
        raise ValueError("Agent版本必须使用major.minor.patch格式。")
    major, minor, patch = value.split(".")
    return int(major), int(minor), int(patch)


class CodexAgentReleaseManifestHeader(BaseModel):
    """发布清单公共头。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["codex_agent_release_manifest"] = AGENT_RELEASE_MANIFEST_KIND
    schema_version: Literal["1.0"] = AGENT_RELEASE_MANIFEST_SCHEMA_VERSION
    channel: Literal["stable"] = "stable"


class CodexAgentReleaseManifestDetail(BaseModel):
    """发布清单强类型扩展字段。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = Field(min_length=1, max_length=64)
    digest_sha256: str = Field(min_length=SHA256_HEX_LENGTH, max_length=SHA256_HEX_LENGTH)
    download_url: str = Field(min_length=1, max_length=2_048)
    rollout_percent: int = Field(ge=0, le=100)
    forced: bool = False
    minimum_security_version: str = Field(min_length=1, max_length=64)
    published_at: datetime

    @field_validator("download_url")
    @classmethod
    def validate_https_url(cls, value: str) -> str:
        """发布地址必须使用 HTTPS。"""

        if not value.startswith("https://"):
            raise ValueError("Agent发布地址必须使用HTTPS。")
        return value

    @field_validator("version", "minimum_security_version")
    @classmethod
    def validate_release_version(cls, value: str) -> str:
        """Require canonical numeric release versions."""

        parse_agent_release_version(value)
        return value

    @model_validator(mode="after")
    def validate_security_floor(self) -> CodexAgentReleaseManifestDetail:
        """A release must be capable of satisfying its own security floor."""

        if parse_agent_release_version(self.minimum_security_version) > parse_agent_release_version(
            self.version
        ):
            raise ValueError("最低安全版本不得高于发布版本。")
        return self


class CodexAgentReleaseManifestEnvelope(BaseModel):
    """发布清单公共头与强类型扩展字段。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    header: CodexAgentReleaseManifestHeader
    detail: CodexAgentReleaseManifestDetail


class CodexAgentReleaseDownloadDetail(BaseModel):
    """登录用户可见的安装包和签名清单入口。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = Field(min_length=1, max_length=64)
    download_url: str = Field(min_length=1, max_length=2_048)
    manifest_url: str = Field(min_length=1, max_length=2_048)
    minimum_security_version: str = Field(min_length=1, max_length=64)

    @field_validator("download_url", "manifest_url")
    @classmethod
    def validate_https_url(cls, value: str) -> str:
        """下载与签名清单入口必须使用 HTTPS。"""

        if not value.startswith("https://"):
            raise ValueError("Agent下载入口必须使用HTTPS。")
        return value


class CodexAgentReleaseDownloadEnvelope(BaseModel):
    """下载入口公共头与强类型扩展字段。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    header: CodexAgentReleaseManifestHeader
    detail: CodexAgentReleaseDownloadDetail
