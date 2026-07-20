"""
统一密钥管理契约模块。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.core.key_management_contract.key_rotation_policy_contract import (
    KeyRotationPolicyEnvelope,
)

KEY_MANAGEMENT_SCHEMA_VERSION: Final = "1.0"
KEY_MANAGEMENT_RUNTIME_KIND: Final = "key_management_runtime"
KEY_MANAGEMENT_HEADER_KIND: Final = "key_management_header"
MANAGED_KEY_FAMILY_KIND: Final = "managed_key_family"
KEY_MANAGEMENT_POLICY_NAME_MINIMUM_LENGTH = 1
KEY_FAMILY_NAME_MINIMUM_LENGTH = 1
KEY_USAGE_MINIMUM_LENGTH = 1


class KeyManagementBackend(StrEnum):
    """
    密钥管理后端枚举。
    """

    CACHE = "cache"


class ManagedKeyFamilyStatus(StrEnum):
    """
    托管密钥族状态枚举。
    """

    ACTIVE = "active"
    DISABLED = "disabled"


class KeyManagementRuntimeHeader(BaseModel):
    """
    密钥管理运行时公共头。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["key_management_header"] = KEY_MANAGEMENT_HEADER_KIND
    schema_version: Literal["1.0"] = KEY_MANAGEMENT_SCHEMA_VERSION
    enabled: bool
    policy_name: str = Field(min_length=KEY_MANAGEMENT_POLICY_NAME_MINIMUM_LENGTH)


class ManagedKeyFamilyEnvelope(BaseModel):
    """
    托管密钥族信封。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["managed_key_family"] = MANAGED_KEY_FAMILY_KIND
    schema_version: Literal["1.0"] = KEY_MANAGEMENT_SCHEMA_VERSION
    family_name: str = Field(min_length=KEY_FAMILY_NAME_MINIMUM_LENGTH)
    usage: str = Field(min_length=KEY_USAGE_MINIMUM_LENGTH)
    enabled: bool
    status: ManagedKeyFamilyStatus = ManagedKeyFamilyStatus.ACTIVE
    current_key_id: str | None = None
    rotation_policy: KeyRotationPolicyEnvelope


class KeyManagementRuntimeDetail(BaseModel):
    """
    密钥管理运行时强类型扩展字段。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["key_management_runtime"] = KEY_MANAGEMENT_RUNTIME_KIND
    schema_version: Literal["1.0"] = KEY_MANAGEMENT_SCHEMA_VERSION
    backend: KeyManagementBackend
    key_families: list[ManagedKeyFamilyEnvelope] = Field(default_factory=list)


KeyManagementRuntimeDetailUnion = Annotated[
    KeyManagementRuntimeDetail,
    Field(discriminator="kind"),
]


class KeyManagementRuntimeEnvelope(BaseModel):
    """
    密钥管理运行时信封。
    """

    model_config = ConfigDict(extra="forbid")

    envelope_kind: Literal["key_management_runtime"] = KEY_MANAGEMENT_RUNTIME_KIND
    schema_version: Literal["1.0"] = KEY_MANAGEMENT_SCHEMA_VERSION
    header: KeyManagementRuntimeHeader
    detail: KeyManagementRuntimeDetailUnion

    @model_validator(mode="after")
    def validate_key_management_contract(self) -> KeyManagementRuntimeEnvelope:
        """
        校验密钥管理公共头与扩展字段一致。
        """

        if self.schema_version != self.header.schema_version:
            raise ValueError("密钥管理 envelope schema_version 必须与 header 一致。")
        if self.header.schema_version != self.detail.schema_version:
            raise ValueError("密钥管理 header schema_version 必须与 detail 一致。")
        return self
