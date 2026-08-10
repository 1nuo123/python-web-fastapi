"""Agent设备认证与用户JWT认证分流契约。"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AgentDevicePrincipal(BaseModel):
    """通过设备凭据解析出的不可变Agent主体。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    credential_id: str = Field(min_length=1)
    host_id: str = Field(min_length=1)
    owner_subject_id: str = Field(min_length=1)


class CodexAgentCredentialIssue(BaseModel):
    """写入设备凭据仓储的脱敏记录。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    credential_id: UUID
    host_id: UUID
    token_digest: str = Field(min_length=64, max_length=64)
    key_id: str = Field(min_length=1, max_length=128)
    status: str = Field(min_length=1, max_length=32)
    issued_at: datetime
    expires_at: datetime | None = None


class AgentDeviceCredentialVerifierPort(Protocol):
    """设备token摘要验证端口。"""

    def verify(self, token: str) -> AgentDevicePrincipal | None:
        """验证设备token，失败时不得泄露匹配细节。"""

        ...
