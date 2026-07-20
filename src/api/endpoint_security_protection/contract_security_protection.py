"""
安全防护管理 API 契约模块。
"""

from __future__ import annotations

from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from src.core.security_contract.security_ip_block_contract import SecurityIpBlockReason

SECURITY_PROTECTION_API_SCHEMA_VERSION: Final = "1.0"
SECURITY_IP_BLOCK_RECORD_PAYLOAD_KIND: Final = "security_ip_block_record_payload"
SECURITY_IP_BLOCK_CREATE_KIND: Final = "security_ip_block_create"
SECURITY_IP_BLOCK_CREATE_PAYLOAD_KIND: Final = "security_ip_block_create_payload"
SECURITY_IP_BLOCK_RELEASE_KIND: Final = "security_ip_block_release"
SECURITY_IP_BLOCK_LIST_KIND: Final = "security_ip_block_list"
IP_BLOCK_QUERY_LIMIT_MINIMUM = 1
IP_BLOCK_QUERY_LIMIT_MAXIMUM = 200
IP_BLOCK_DIGEST_MINIMUM_LENGTH = 12
IP_BLOCK_REASON_MINIMUM_LENGTH = 1
IP_BLOCK_SECONDS_MINIMUM = 1


class SecurityIpBlockRecordPayload(BaseModel):
    """
    安全 IP 封禁记录响应载荷。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["security_ip_block_record_payload"] = SECURITY_IP_BLOCK_RECORD_PAYLOAD_KIND
    schema_version: Literal["1.0"] = SECURITY_PROTECTION_API_SCHEMA_VERSION
    record_id: str
    ip_digest: str
    reason: str
    status: str
    blocked_until_epoch: int
    released_reason: str | None


class SecurityIpBlockListPayload(BaseModel):
    """
    安全 IP 封禁列表响应载荷。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["security_ip_block_list"] = SECURITY_IP_BLOCK_LIST_KIND
    schema_version: Literal["1.0"] = SECURITY_PROTECTION_API_SCHEMA_VERSION
    records: list[SecurityIpBlockRecordPayload]


class SecurityIpBlockCreateRequest(BaseModel):
    """
    安全 IP 手动封禁请求。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["security_ip_block_create"] = SECURITY_IP_BLOCK_CREATE_KIND
    schema_version: Literal["1.0"] = SECURITY_PROTECTION_API_SCHEMA_VERSION
    ip_digest: str = Field(min_length=IP_BLOCK_DIGEST_MINIMUM_LENGTH)
    reason: SecurityIpBlockReason = SecurityIpBlockReason.MANUAL
    block_seconds: int = Field(ge=IP_BLOCK_SECONDS_MINIMUM)


class SecurityIpBlockCreatePayload(BaseModel):
    """
    安全 IP 手动封禁响应载荷。

    :ivar kind: 响应载荷类型。
    :vartype kind: Literal[SECURITY_IP_BLOCK_CREATE_PAYLOAD_KIND]
    :ivar schema_version: 契约版本。
    :vartype schema_version: Literal[SECURITY_PROTECTION_API_SCHEMA_VERSION]
    :ivar record: 封禁记录。
    :vartype record: SecurityIpBlockRecordPayload
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["security_ip_block_create_payload"] = SECURITY_IP_BLOCK_CREATE_PAYLOAD_KIND
    schema_version: Literal["1.0"] = SECURITY_PROTECTION_API_SCHEMA_VERSION
    record: SecurityIpBlockRecordPayload


class SecurityIpBlockReleaseRequest(BaseModel):
    """
    安全 IP 封禁释放请求。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["security_ip_block_release"] = SECURITY_IP_BLOCK_RELEASE_KIND
    schema_version: Literal["1.0"] = SECURITY_PROTECTION_API_SCHEMA_VERSION
    ip_digest: str = Field(min_length=IP_BLOCK_DIGEST_MINIMUM_LENGTH)
    released_reason: str = Field(min_length=IP_BLOCK_REASON_MINIMUM_LENGTH)


class SecurityIpBlockReleasePayload(BaseModel):
    """
    安全 IP 封禁释放响应载荷。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["security_ip_block_release"] = SECURITY_IP_BLOCK_RELEASE_KIND
    schema_version: Literal["1.0"] = SECURITY_PROTECTION_API_SCHEMA_VERSION
    ip_digest: str
    released: bool
