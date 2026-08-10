"""Codex 设备授权审计契约。"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.core.codex_contract.device_authorization_contract import (
    DeviceAuthorizationDecision,
)


class DeviceAuthorizationAuditSnapshot(BaseModel):
    """与主机和设备公钥同事务写入的授权决定。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    audit_id: UUID
    enrollment_id: UUID
    host_id: UUID | None = None
    owner_subject_id: str = Field(min_length=1, max_length=128)
    decision: DeviceAuthorizationDecision
    idempotency_key: str = Field(min_length=8, max_length=128)
    occurred_at: datetime
