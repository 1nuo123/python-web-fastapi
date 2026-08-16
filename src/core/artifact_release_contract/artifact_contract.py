"""与 Codex 业务无关的制品身份、校验和激活契约。"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

ARTIFACT_SCHEMA_VERSION: Final = "1.0"
SHA256_LENGTH = 64


class ArtifactPlatform(StrEnum):
    """制品目标平台。"""

    WINDOWS = "windows"
    LINUX = "linux"
    MACOS = "macos"


class ArtifactArchitecture(StrEnum):
    """制品目标架构。"""

    X86_64 = "x86_64"
    ARM64 = "arm64"


class ArtifactChannel(StrEnum):
    """发布渠道。"""

    STABLE = "stable"
    BETA = "beta"


class ArtifactActivationState(StrEnum):
    """本地版本激活状态。"""

    STAGED = "staged"
    ACTIVE = "active"
    HEALTHY = "healthy"
    COMMITTED = "committed"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"


class ArtifactIdentity(BaseModel):
    """制品唯一身份，不包含业务产品字段。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_name: str = Field(min_length=1, max_length=128)
    platform: ArtifactPlatform
    architecture: ArtifactArchitecture
    channel: ArtifactChannel
    version: str = Field(min_length=1, max_length=128)
    digest_sha256: str = Field(min_length=SHA256_LENGTH, max_length=SHA256_LENGTH)


class ArtifactSignatureDetail(BaseModel):
    """制品签名校验摘要。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    method: Literal["authenticode", "detached"]
    signer_subject: str | None = Field(default=None, max_length=256)
    signer_sha256: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-fA-F]{64}$",
    )
    verified_at: datetime


class TufTargetMetadata(BaseModel):
    """已由 python-tuf 验证的 target 元数据摘要。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    target_path: str = Field(min_length=1, max_length=512)
    length: int = Field(gt=0)
    hashes: dict[str, str] = Field(min_length=1)
    custom: dict[str, str] = Field(default_factory=dict)


class ArtifactReleaseEnvelope(BaseModel):
    """通用制品发布公共头与强类型扩展字段。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = ARTIFACT_SCHEMA_VERSION
    identity: ArtifactIdentity
    signature: ArtifactSignatureDetail | None = None
    tuf_target: TufTargetMetadata | None = None


class ArtifactActivationRecord(BaseModel):
    """本地版本目录的持久化激活状态。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    identity: ArtifactIdentity
    state: ArtifactActivationState
    staged_path: Path
    activated_at: datetime | None = None
    last_error_code: str | None = Field(default=None, max_length=128)


class ArtifactVerificationResult(BaseModel):
    """下载制品校验结果。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    identity: ArtifactIdentity
    digest_verified: bool
    signature_verified: bool
    signature: ArtifactSignatureDetail | None = None


class ArtifactReleaseStep(StrEnum):
    """发布编排阶段。"""

    RESOLVE = "resolve"
    DOWNLOAD = "download"
    VERIFY = "verify"
    STAGE = "stage"
    ACTIVATE = "activate"
    HEALTH = "health"
    COMMIT = "commit"
    ROLLBACK = "rollback"


class ArtifactReleaseResult(BaseModel):
    """可恢复发布结果。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    identity: ArtifactIdentity
    completed_steps: tuple[ArtifactReleaseStep, ...]
    activation: ArtifactActivationRecord
    rollback_performed: bool = False
    failure_code: str | None = Field(default=None, max_length=128)
