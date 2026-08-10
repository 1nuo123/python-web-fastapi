"""Codex 设备公钥、挑战与连接票据契约。"""

from __future__ import annotations

import json
from datetime import datetime
from enum import StrEnum
from typing import Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

DEVICE_CHALLENGE_AUDIENCE: Final = "codex.agent.challenge"
DEVICE_CONNECTION_OPERATION: Final = "codex.agent.connect"
DEVICE_CHALLENGE_CANONICAL_KIND: Final = "codex_device_challenge"
DEVICE_CHALLENGE_CANONICAL_VERSION: Final = "1.0"


class DeviceKeyState(StrEnum):
    """设备公钥生命周期状态。"""

    PENDING = "pending"
    ACTIVE = "active"
    ROTATING = "rotating"
    REVOKED = "revoked"
    EXPIRED = "expired"


class CodexDeviceKeySnapshot(BaseModel):
    """PostgreSQL 设备公钥行的强类型快照。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    key_id: UUID
    enrollment_id: UUID
    host_id: UUID
    owner_subject_id: str = Field(min_length=1, max_length=128)
    public_key: bytes = Field(min_length=32, max_length=32)
    fingerprint: str = Field(min_length=64, max_length=64)
    state: DeviceKeyState
    version: int = Field(ge=1)
    activated_at: datetime | None = None
    revoked_at: datetime | None = None
    retire_after: datetime | None = None
    created_at: datetime
    updated_at: datetime


class DeviceChallengeIssue(BaseModel):
    """服务端签名挑战。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    challenge_id: UUID
    host_id: UUID
    key_id: UUID
    nonce: str = Field(min_length=32, max_length=256)
    audience: str = Field(min_length=1, max_length=128)
    issued_at: datetime
    expires_at: datetime


class DeviceChallengeIssueRequest(BaseModel):
    """Agent 申请挑战的强类型扩展字段。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["challenge.issue"] = "challenge.issue"
    host_id: UUID
    key_id: UUID


class DeviceChallengeProof(BaseModel):
    """Agent 对 canonical challenge bytes 的签名证明。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["challenge.proof"] = "challenge.proof"
    challenge_id: UUID
    host_id: UUID
    key_id: UUID
    signature_base64: str = Field(min_length=86, max_length=256)


class DeviceChallengeRequestHeader(BaseModel):
    """设备挑战 HTTP 请求公共头。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["codex_device_challenge"] = "codex_device_challenge"
    schema_version: Literal["1.0"] = "1.0"
    request_id: UUID


class DeviceChallengeIssueRequestEnvelope(BaseModel):
    """挑战签发请求信封。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    header: DeviceChallengeRequestHeader
    detail: DeviceChallengeIssueRequest


class DeviceChallengeProofRequestEnvelope(BaseModel):
    """挑战证明请求信封。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    header: DeviceChallengeRequestHeader
    detail: DeviceChallengeProof


class DeviceKeyRotationStartDetail(BaseModel):
    """旧 key 证明通过后登记新公钥的请求扩展。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["key_rotation.start"] = "key_rotation.start"
    proof: DeviceChallengeProof
    new_key_id: UUID
    display_name: str = Field(min_length=1, max_length=128)
    platform: str = Field(min_length=1, max_length=64)
    public_key_base64: str = Field(min_length=43, max_length=128)
    nonce: str = Field(min_length=32, max_length=256)
    nonce_signature_base64: str = Field(min_length=86, max_length=256)


class DeviceKeyRotationStartRequestEnvelope(BaseModel):
    """设备 key rotation 公共头与强类型扩展字段。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    header: DeviceChallengeRequestHeader
    detail: DeviceKeyRotationStartDetail


class DeviceChallengeCanonicalMessage(BaseModel):
    """Ed25519 签名覆盖的稳定 canonical message。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: str = DEVICE_CHALLENGE_CANONICAL_KIND
    schema_version: str = DEVICE_CHALLENGE_CANONICAL_VERSION
    challenge_id: UUID
    host_id: UUID
    key_id: UUID
    nonce: str = Field(min_length=32, max_length=256)
    audience: str = Field(min_length=1, max_length=128)
    issued_at: datetime
    expires_at: datetime

    def canonical_bytes(self) -> bytes:
        """使用排序键和固定分隔符构造签名字节。"""

        payload = self.model_dump(mode="json")
        return json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")


class DeviceChallengeStoreRecord(BaseModel):
    """原子状态中一次性挑战的完整受信记录。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    challenge: DeviceChallengeIssue
    owner_subject_id: str = Field(min_length=1, max_length=128)
    version: int = Field(ge=1)


class AgentConnectionTicketSubject(BaseModel):
    """编码进通用 ticket subject 的强类型 Agent 身份。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    host_id: UUID
    key_id: UUID
    owner_subject_id: str = Field(min_length=1, max_length=128)

    def encode(self) -> str:
        """编码为通用流票据可保存的稳定主体字符串。"""

        return self.model_dump_json()

    @classmethod
    def decode(cls, value: str) -> AgentConnectionTicketSubject:
        """从已消费票据的主体字符串恢复强类型身份。"""

        return cls.model_validate_json(value)


class AgentConnectionTicketResponse(BaseModel):
    """一次性短期 Agent WSS ticket。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ticket: str = Field(min_length=32, max_length=512)
    expires_at: datetime
