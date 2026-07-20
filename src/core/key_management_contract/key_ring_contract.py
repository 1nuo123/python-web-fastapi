"""
密钥环契约模块。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

KEY_RING_SCHEMA_VERSION: Final = "1.0"
MANAGED_KEY_DESCRIPTOR_KIND: Final = "managed_key_descriptor"
KEY_RING_SNAPSHOT_KIND: Final = "key_ring_snapshot"
KEY_IDENTIFIER_MINIMUM_LENGTH = 1
KEY_FAMILY_MINIMUM_LENGTH = 1
KEY_DIGEST_MINIMUM_LENGTH = 12
KEY_MATERIAL_MINIMUM_LENGTH = 16
TIMESTAMP_MINIMUM_VALUE = 0


class ManagedKeyStatus(StrEnum):
    """
    托管密钥状态枚举。
    """

    CURRENT = "current"
    ACTIVE = "active"
    RETIRED = "retired"


class ManagedKeyDescriptor(BaseModel):
    """
    托管密钥描述。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["managed_key_descriptor"] = MANAGED_KEY_DESCRIPTOR_KIND
    schema_version: Literal["1.0"] = KEY_RING_SCHEMA_VERSION
    key_id: str = Field(min_length=KEY_IDENTIFIER_MINIMUM_LENGTH)
    key_digest: str = Field(min_length=KEY_DIGEST_MINIMUM_LENGTH)
    key_material: str = Field(min_length=KEY_MATERIAL_MINIMUM_LENGTH)
    status: ManagedKeyStatus
    not_before_epoch: int = Field(ge=TIMESTAMP_MINIMUM_VALUE)
    expires_at_epoch: int = Field(ge=TIMESTAMP_MINIMUM_VALUE)


class KeyRingSnapshot(BaseModel):
    """
    密钥环快照。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["key_ring_snapshot"] = KEY_RING_SNAPSHOT_KIND
    schema_version: Literal["1.0"] = KEY_RING_SCHEMA_VERSION
    key_family: str = Field(min_length=KEY_FAMILY_MINIMUM_LENGTH)
    current_key_id: str = Field(min_length=KEY_IDENTIFIER_MINIMUM_LENGTH)
    candidate_key_ids: list[str] = Field(default_factory=list)
    valid_key_digests: list[str] = Field(default_factory=list)
    next_rotation_epoch: int = Field(ge=TIMESTAMP_MINIMUM_VALUE)
    keys: list[ManagedKeyDescriptor] = Field(min_length=1)
