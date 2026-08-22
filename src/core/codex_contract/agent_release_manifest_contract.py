"""Codex Remote Agent 发布清单公共契约。"""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from typing import Final, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

AGENT_RELEASE_MANIFEST_KIND: Final = "codex_agent_release_manifest"
AGENT_RELEASE_MANIFEST_SCHEMA_VERSION: Final = "1.0"
AGENT_RELEASE_MANIFEST_TARGET_PATH: Final = "codex-agent-release.json"
SHA256_HEX_LENGTH: Final = 64
AGENT_RELEASE_VERSION_PATTERN: Final = re.compile(r"^\d+\.\d+\.\d+$")
SHA256_HEX_PATTERN: Final = re.compile(r"^[0-9a-f]{64}$")
INTERNAL_RELEASE_MUTABLE_PATH_SEGMENTS: Final = frozenset({"latest", "main", "master"})
INTERNAL_AGENT_RELEASE_MANIFEST_KIND: Final = "codex_agent_internal_release"
INTERNAL_AGENT_RELEASE_MANIFEST_SCHEMA_VERSION: Final = "1.0"
INTERNAL_AGENT_INSTALLER_FILE_NAME: Final = "CodexRemoteAgent.msi"


class CodexAgentReleaseDistributionMode(StrEnum):
    """面向浏览器下载入口的发布保障等级。

    ``verified`` 保留正式 TUF 发布语义；``internal`` 仅用于经明确确认的
    内部体验包，Agent 不会从该通道自动更新。
    """

    VERIFIED = "verified"
    INTERNAL = "internal"


def parse_agent_release_version(value: str) -> tuple[int, int, int]:
    """Parse the canonical three-part Agent release version."""

    if AGENT_RELEASE_VERSION_PATTERN.fullmatch(value) is None:
        raise ValueError("Agent版本必须使用major.minor.patch格式。")
    major, minor, patch = value.split(".")
    return int(major), int(minor), int(patch)


def validate_agent_release_sha256(value: str) -> str:
    """校验公开制品摘要为可直接给用户核对的小写 SHA-256。"""

    if SHA256_HEX_PATTERN.fullmatch(value) is None:
        raise ValueError("Agent制品SHA-256必须是64位小写十六进制字符串。")
    return value


def validate_internal_agent_release_url(value: str, *, version: str) -> str:
    """校验内部体验包使用无查询参数的版本化 HTTPS 地址。

    内部通道不具备 TUF 的可撤销元数据，因此不能把可变分支、latest 指针或
    带凭据的 URL 交给下载页。版本目录/标签至少要显式包含当前版本，便于
    发布流程把同一版本视为不可覆盖的制品槽位。
    """

    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("内部体验包地址必须是不含凭据、查询或片段的HTTPS地址。")
    path_segments = tuple(segment.lower() for segment in parsed.path.split("/") if segment)
    if INTERNAL_RELEASE_MUTABLE_PATH_SEGMENTS.intersection(path_segments):
        raise ValueError("内部体验包地址不得引用master、main或latest等可变路径。")
    release_version = parse_agent_release_version(version)
    canonical_version = ".".join(str(part) for part in release_version)
    if canonical_version not in path_segments and f"v{canonical_version}" not in path_segments:
        raise ValueError("内部体验包地址必须显式包含当前发布版本目录或标签。")
    return value


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


class CodexAgentInternalReleaseManifestHeader(BaseModel):
    """内部体验发布清单的固定公共头，不能被误当作 TUF 元数据。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["codex_agent_internal_release"] = INTERNAL_AGENT_RELEASE_MANIFEST_KIND
    schema_version: Literal["1.0"] = INTERNAL_AGENT_RELEASE_MANIFEST_SCHEMA_VERSION
    channel: Literal["internal"] = "internal"


class CodexAgentInternalReleaseManifestDetail(BaseModel):
    """供下载者手工核验的内部体验包制品信息。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = Field(min_length=1, max_length=64)
    artifact_name: Literal["CodexRemoteAgent.msi"] = INTERNAL_AGENT_INSTALLER_FILE_NAME
    artifact_sha256: str = Field(min_length=SHA256_HEX_LENGTH, max_length=SHA256_HEX_LENGTH)
    download_url: str = Field(min_length=1, max_length=2_048)
    automatic_updates_enabled: Literal[False] = False
    published_at: datetime

    @field_validator("version")
    @classmethod
    def validate_release_version(cls, value: str) -> str:
        """内部包沿用 Windows MSI 的三段版本边界。"""

        parse_agent_release_version(value)
        return value

    @field_validator("artifact_sha256")
    @classmethod
    def validate_artifact_sha256(cls, value: str) -> str:
        """禁止把不完整或大小写不一致的摘要写入公开清单。"""

        return validate_agent_release_sha256(value)

    @model_validator(mode="after")
    def validate_download_url(self) -> CodexAgentInternalReleaseManifestDetail:
        """内部清单只能指向当前版本的不可变下载地址。"""

        validate_internal_agent_release_url(self.download_url, version=self.version)
        return self


class CodexAgentInternalReleaseManifestEnvelope(BaseModel):
    """内部体验包的独立清单，不提供 TUF 或自动更新承诺。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    header: CodexAgentInternalReleaseManifestHeader
    detail: CodexAgentInternalReleaseManifestDetail


class CodexAgentReleaseDownloadDetail(BaseModel):
    """登录用户可见的安装包、核验摘要和发布说明入口。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = Field(min_length=1, max_length=64)
    distribution_mode: CodexAgentReleaseDistributionMode
    artifact_sha256: str = Field(min_length=SHA256_HEX_LENGTH, max_length=SHA256_HEX_LENGTH)
    download_url: str = Field(min_length=1, max_length=2_048)
    manifest_url: str = Field(min_length=1, max_length=2_048)
    minimum_security_version: str = Field(min_length=1, max_length=64)
    automatic_updates_enabled: bool

    @field_validator("download_url", "manifest_url")
    @classmethod
    def validate_https_url(cls, value: str) -> str:
        """下载与发布清单入口必须使用 HTTPS。"""

        if not value.startswith("https://"):
            raise ValueError("Agent下载入口必须使用HTTPS。")
        return value

    @field_validator("version", "minimum_security_version")
    @classmethod
    def validate_release_version(cls, value: str) -> str:
        """浏览器不得得到 Agent 无法识别的版本号。"""

        parse_agent_release_version(value)
        return value

    @field_validator("artifact_sha256")
    @classmethod
    def validate_artifact_sha256(cls, value: str) -> str:
        """公开下载页只接受可复制核验的小写摘要。"""

        return validate_agent_release_sha256(value)

    @model_validator(mode="after")
    def validate_distribution_boundary(self) -> CodexAgentReleaseDownloadDetail:
        """把内部体验包与正式 TUF 发布的浏览器语义显式隔离。"""

        if self.distribution_mode is CodexAgentReleaseDistributionMode.INTERNAL:
            if self.automatic_updates_enabled:
                raise ValueError("内部体验包不得启用自动更新。")
            validate_internal_agent_release_url(self.download_url, version=self.version)
            validate_internal_agent_release_url(self.manifest_url, version=self.version)
        return self


class CodexAgentReleaseDownloadEnvelope(BaseModel):
    """下载入口公共头与强类型扩展字段。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    header: CodexAgentReleaseManifestHeader
    detail: CodexAgentReleaseDownloadDetail
