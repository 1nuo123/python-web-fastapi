"""Codex 已认证设备注册意图公共契约。"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.core.codex_contract.device_authorization_contract import (
    DeviceAuthorizationCreateDetail,
    DeviceAuthorizationEnvelope,
)
from src.core.codex_contract.device_key_contract import DeviceChallengeProof

CODEX_ENROLLMENT_INTENT_KIND: Final = "codex_enrollment_intent"
CODEX_ENROLLMENT_INTENT_SCHEMA_VERSION: Final = "1.0"
CODEX_ENROLLMENT_LAUNCH_URI_PATTERN: Final = r"^(?:codexremote|codexremote-dev)://enroll\?token="


class CodexEnrollmentIntentState(StrEnum):
    """注册意图生命周期状态。"""

    ISSUED = "issued"
    CONSUMING = "consuming"
    CONSUMED = "consumed"


class CodexEnrollmentIntentHeader(BaseModel):
    """注册意图公共头字段。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["codex_enrollment_intent"] = CODEX_ENROLLMENT_INTENT_KIND
    schema_version: Literal["1.0"] = CODEX_ENROLLMENT_INTENT_SCHEMA_VERSION
    intent_id: UUID


class CodexEnrollmentIntentRequestHeader(BaseModel):
    """注册意图 HTTP 请求公共头字段。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["codex_enrollment_intent"] = CODEX_ENROLLMENT_INTENT_KIND
    schema_version: Literal["1.0"] = CODEX_ENROLLMENT_INTENT_SCHEMA_VERSION
    request_id: UUID


class CodexEnrollmentIntentCreateDetail(BaseModel):
    """浏览器创建注册意图的强类型扩展字段。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    return_path: str = Field(default="/codex/verify-device", pattern=r"^/codex/[a-z0-9/_-]*$")


class CodexEnrollmentIntentCreateRequestEnvelope(BaseModel):
    """浏览器创建注册意图请求信封。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    header: CodexEnrollmentIntentRequestHeader
    detail: CodexEnrollmentIntentCreateDetail


class CodexEnrollmentIntentIssuedDetail(BaseModel):
    """浏览器收到的一次性注册意图。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    state: Literal[CodexEnrollmentIntentState.ISSUED]
    launch_uri: str = Field(pattern=CODEX_ENROLLMENT_LAUNCH_URI_PATTERN)
    expires_at: datetime


class CodexEnrollmentIntentStatusDetail(BaseModel):
    """浏览器可读取的注册意图状态。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    state: CodexEnrollmentIntentState
    expires_at: datetime
    user_code: str | None = Field(default=None, min_length=6, max_length=16)
    authorization: DeviceAuthorizationEnvelope | None = None
    host_id: UUID | None = None


class CodexEnrollmentIntentConsumeDetail(BaseModel):
    """Agent 使用一次性 token 创建设备授权的强类型扩展字段。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    intent_token: str = Field(min_length=32, max_length=512)
    authorization: DeviceAuthorizationCreateDetail


class CodexEnrollmentIntentConsumeRequestEnvelope(BaseModel):
    """Agent 消费注册意图请求信封。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    header: CodexEnrollmentIntentRequestHeader
    detail: CodexEnrollmentIntentConsumeDetail


class CodexEnrollmentIntentResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    intent_token: str = Field(min_length=32, max_length=512)
    proof: DeviceChallengeProof


CodexEnrollmentIntentDetail = CodexEnrollmentIntentIssuedDetail | CodexEnrollmentIntentStatusDetail


class CodexEnrollmentIntentEnvelope(BaseModel):
    """注册意图公共头与强类型扩展字段信封。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    header: CodexEnrollmentIntentHeader
    detail: CodexEnrollmentIntentDetail


class CodexEnrollmentIntentStoreRecord(BaseModel):
    """短期分布式状态中的注册意图记录。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    intent_id: UUID
    token_digest: str = Field(min_length=64, max_length=64)
    subject_id: str = Field(min_length=1, max_length=128)
    token_session_id: UUID
    verification_uri: str = Field(min_length=1, max_length=2048)
    state: CodexEnrollmentIntentState
    version: int = Field(ge=1)
    enrollment_id: UUID | None = None
    user_code: str | None = Field(default=None, min_length=6, max_length=16)
    device_code: str | None = Field(default=None, min_length=32, max_length=512)
    poll_interval_seconds: int | None = Field(default=None, ge=1, le=60)
    authorization_expires_at: datetime | None = None
    request_digest: str | None = None
    host_id: UUID | None = None
    expires_at: datetime
