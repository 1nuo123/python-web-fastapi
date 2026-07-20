"""
IP 封禁契约模块。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

SECURITY_IP_BLOCK_SCHEMA_VERSION: Final = "1.0"
SECURITY_IP_BLOCK_RECORD_KIND: Final = "security_ip_block_record"
IP_BLOCK_CACHE_ENTRY_KIND: Final = "ip_block_cache_entry"
IP_BLOCK_DIGEST_MINIMUM_LENGTH = 12
IP_BLOCK_REASON_MINIMUM_LENGTH = 1
IP_BLOCK_EPOCH_MINIMUM_VALUE = 0


class SecurityIpBlockStatus(StrEnum):
    """
    IP 封禁状态枚举。
    """

    ACTIVE = "active"
    RELEASED = "released"
    EXPIRED = "expired"


class SecurityIpBlockReason(StrEnum):
    """
    IP 封禁原因枚举。
    """

    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    RISK_SIGNAL_EXCEEDED = "risk_signal_exceeded"
    MANUAL = "manual"


class SecurityIpBlockEnvelope(BaseModel):
    """
    IP 封禁记录信封。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["security_ip_block_record"] = SECURITY_IP_BLOCK_RECORD_KIND
    schema_version: Literal["1.0"] = SECURITY_IP_BLOCK_SCHEMA_VERSION
    record_id: str
    ip_digest: str = Field(min_length=IP_BLOCK_DIGEST_MINIMUM_LENGTH)
    reason: SecurityIpBlockReason
    status: SecurityIpBlockStatus
    blocked_until_epoch: int = Field(ge=IP_BLOCK_EPOCH_MINIMUM_VALUE)
    released_reason: str | None = None


class IpBlockCacheEntry(BaseModel):
    """
    IP 封禁缓存项。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["ip_block_cache_entry"] = IP_BLOCK_CACHE_ENTRY_KIND
    schema_version: Literal["1.0"] = SECURITY_IP_BLOCK_SCHEMA_VERSION
    blocked_until_epoch: int = Field(ge=IP_BLOCK_EPOCH_MINIMUM_VALUE)
    reason: SecurityIpBlockReason
