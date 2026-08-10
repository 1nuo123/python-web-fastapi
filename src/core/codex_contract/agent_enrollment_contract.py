"""Codex 主机配对、Agent enroll 与凭据轮换接口契约。"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CodexPairingCodeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=128)
    platform: str = Field(min_length=1, max_length=64)


class CodexPairingCodeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host_id: UUID
    pairing_code: str = Field(min_length=32, max_length=256)
    expires_at: datetime


class CodexAgentEnrollRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host_id: UUID
    pairing_code: str = Field(min_length=32, max_length=256)


class CodexAgentCredentialResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    credential_id: UUID
    device_token: str = Field(min_length=32, max_length=512)
