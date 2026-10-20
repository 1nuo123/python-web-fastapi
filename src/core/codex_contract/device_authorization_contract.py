"""Codex 设备授权公共头与强类型扩展字段契约。"""

from __future__ import annotations

import json
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from src.core.codex_contract.device_key_contract import DeviceChallengeProof

DEVICE_AUTHORIZATION_KIND: Final = "codex_device_authorization"
DEVICE_AUTHORIZATION_SCHEMA_VERSION: Final = "1.0"


class DeviceAuthorizationRecoveryRequest(BaseModel):
    """同一设备 key 的批准结果恢复；proof 缺省时只申请用途绑定挑战。"""

    model_config = ConfigDict(extra="forbid", frozen=True)
    enrollment_id: UUID
    key_id: UUID
    proof: DeviceChallengeProof | None = None


class DeviceAuthorizationRecoveryResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    enrollment_id: UUID
    host_id: UUID
    key_id: UUID
    activated: Literal[True] = True


class DeviceAuthorizationState(StrEnum):
    """设备授权状态封闭集合。"""

    PENDING_USER = "pending_user"
    APPROVING = "approving"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    CONSUMED = "consumed"


class DeviceAuthorizationDecision(StrEnum):
    """浏览器对设备请求的决定。"""

    APPROVE = "approve"
    DENY = "deny"


class DeviceAuthorizationHeader(BaseModel):
    """所有设备授权消息的公共头。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["codex_device_authorization"] = DEVICE_AUTHORIZATION_KIND
    schema_version: Literal["1.0"] = DEVICE_AUTHORIZATION_SCHEMA_VERSION
    enrollment_id: UUID


class DeviceAuthorizationRequestHeader(BaseModel):
    """设备授权 HTTP 请求的公共头。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["codex_device_authorization"] = DEVICE_AUTHORIZATION_KIND
    schema_version: Literal["1.0"] = DEVICE_AUTHORIZATION_SCHEMA_VERSION
    request_id: UUID


class DeviceAuthorizationCreateDetail(BaseModel):
    """Agent 创建设备授权的输入。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["create"] = "create"
    key_id: UUID
    display_name: str = Field(min_length=1, max_length=128)
    platform: str = Field(min_length=1, max_length=64)
    public_key_base64: str = Field(min_length=43, max_length=128)
    nonce: str = Field(min_length=32, max_length=256)
    nonce_signature_base64: str = Field(min_length=86, max_length=256)


class DeviceEnrollmentCanonicalMessage(BaseModel):
    """首次授权请求的 Ed25519 proof-of-possession 消息。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["codex_device_enrollment_proof"] = "codex_device_enrollment_proof"
    schema_version: Literal["1.0"] = DEVICE_AUTHORIZATION_SCHEMA_VERSION
    key_id: UUID
    display_name: str = Field(min_length=1, max_length=128)
    platform: str = Field(min_length=1, max_length=64)
    public_key_fingerprint: str = Field(min_length=64, max_length=64)
    nonce: str = Field(min_length=32, max_length=256)

    def canonical_bytes(self) -> bytes:
        """使用固定 JSON 规则构造签名字节。"""

        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")


class DeviceAuthorizationIssuedDetail(BaseModel):
    """仅创建响应中返回一次的 device code 与 user code。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["issued"] = "issued"
    device_code: str = Field(min_length=32, max_length=256)
    user_code: str = Field(min_length=6, max_length=16)
    verification_uri: str = Field(min_length=1, max_length=2_048)
    interval_seconds: int = Field(ge=1, le=60)
    expires_at: datetime


class DeviceAuthorizationStatusDetail(BaseModel):
    """Agent 轮询或浏览器读取的脱敏状态。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["status"] = "status"
    state: DeviceAuthorizationState
    display_name: str = Field(min_length=1, max_length=128)
    platform: str = Field(min_length=1, max_length=64)
    public_key_fingerprint: str = Field(min_length=64, max_length=64)
    interval_seconds: int = Field(ge=1, le=60)
    expires_at: datetime
    host_id: UUID | None = None
    key_id: UUID | None = None


DeviceAuthorizationDetail = Annotated[
    DeviceAuthorizationCreateDetail
    | DeviceAuthorizationIssuedDetail
    | DeviceAuthorizationStatusDetail,
    Field(discriminator="kind"),
]


class DeviceAuthorizationEnvelope(BaseModel):
    """设备授权公共头与强类型扩展字段信封。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    header: DeviceAuthorizationHeader
    detail: DeviceAuthorizationDetail


class DeviceAuthorizationPollRequest(BaseModel):
    """Agent 使用 device code 轮询。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    enrollment_id: UUID
    device_code: str = Field(min_length=32, max_length=256)


class DeviceAuthorizationCreateRequestEnvelope(BaseModel):
    """Agent 创建设备授权的公共头与强类型扩展字段。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    header: DeviceAuthorizationRequestHeader
    detail: DeviceAuthorizationCreateDetail


class DeviceAuthorizationPollRequestEnvelope(BaseModel):
    """Agent 轮询设备授权的公共头与强类型扩展字段。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    header: DeviceAuthorizationRequestHeader
    detail: DeviceAuthorizationPollRequest


class DeviceAuthorizationReadRequest(BaseModel):
    """浏览器按 user code 读取待批准设备。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    user_code: str = Field(min_length=6, max_length=16)


class DeviceAuthorizationDecideRequest(BaseModel):
    """浏览器批准或拒绝设备。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    enrollment_id: UUID
    user_code: str = Field(min_length=6, max_length=16)
    decision: DeviceAuthorizationDecision
    idempotency_key: str = Field(min_length=8, max_length=128)


class DeviceAuthorizationDecideRequestEnvelope(BaseModel):
    """浏览器决定设备授权的公共头与强类型扩展字段。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    header: DeviceAuthorizationRequestHeader
    detail: DeviceAuthorizationDecideRequest


class DeviceAuthorizationStoreRecord(BaseModel):
    """短期分布式状态中的设备授权记录，不保存明文 code。"""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        ser_json_bytes="base64",
        val_json_bytes="base64",
    )

    enrollment_id: UUID
    device_code_digest: str = Field(min_length=64, max_length=64)
    user_code_digest: str = Field(min_length=64, max_length=64)
    display_name: str = Field(min_length=1, max_length=128)
    platform: str = Field(min_length=1, max_length=64)
    public_key: bytes = Field(min_length=32, max_length=32)
    public_key_fingerprint: str = Field(min_length=64, max_length=64)
    requested_key_id: UUID
    state: DeviceAuthorizationState
    version: int = Field(ge=1)
    poll_interval_seconds: int = Field(ge=1, le=60)
    last_poll_at: datetime | None = None
    poll_attempts: int = Field(ge=0)
    user_code_attempts: int = Field(ge=0)
    owner_subject_id: str | None = Field(default=None, max_length=128)
    host_id: UUID | None = None
    key_id: UUID | None = None
    rotation_host_id: UUID | None = None
    rotation_old_key_id: UUID | None = None
    expires_at: datetime
