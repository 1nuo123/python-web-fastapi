"""
分布式锁契约模块。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

DISTRIBUTED_LOCK_SCHEMA_VERSION: Final = "1.0"
DISTRIBUTED_LOCK_RUNTIME_KIND: Final = "distributed_lock_runtime"
DISTRIBUTED_LOCK_HEADER_KIND: Final = "distributed_lock_header"
DISTRIBUTED_LOCK_REQUEST_KIND: Final = "distributed_lock_request"
DISTRIBUTED_LOCK_LEASE_KIND: Final = "distributed_lock_lease"
DISTRIBUTED_LOCK_POLICY_NAME_MINIMUM_LENGTH = 1
DISTRIBUTED_LOCK_NAMESPACE_MINIMUM_LENGTH = 1
DISTRIBUTED_LOCK_KEY_DIGEST_MINIMUM_LENGTH = 12
DISTRIBUTED_LOCK_OWNER_MINIMUM_LENGTH = 1
DISTRIBUTED_LOCK_TTL_MINIMUM_SECONDS = 1
DISTRIBUTED_LOCK_WAIT_MINIMUM_SECONDS = 0
DISTRIBUTED_LOCK_EXPIRES_AT_MINIMUM = 0


class DistributedLockBackend(StrEnum):
    """
    分布式锁后端枚举。
    """

    CACHE = "cache"


class DistributedLockRuntimeHeader(BaseModel):
    """
    分布式锁运行时公共头。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["distributed_lock_header"] = DISTRIBUTED_LOCK_HEADER_KIND
    schema_version: Literal["1.0"] = DISTRIBUTED_LOCK_SCHEMA_VERSION
    enabled: bool
    policy_name: str = Field(min_length=DISTRIBUTED_LOCK_POLICY_NAME_MINIMUM_LENGTH)


class DistributedLockRuntimeDetail(BaseModel):
    """
    分布式锁运行时强类型扩展字段。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["distributed_lock_runtime"] = DISTRIBUTED_LOCK_RUNTIME_KIND
    schema_version: Literal["1.0"] = DISTRIBUTED_LOCK_SCHEMA_VERSION
    backend: DistributedLockBackend
    lease_seconds: int = Field(ge=DISTRIBUTED_LOCK_TTL_MINIMUM_SECONDS)
    wait_seconds: int = Field(ge=DISTRIBUTED_LOCK_WAIT_MINIMUM_SECONDS)


DistributedLockRuntimeDetailUnion = Annotated[
    DistributedLockRuntimeDetail,
    Field(discriminator="kind"),
]


class DistributedLockRuntimeEnvelope(BaseModel):
    """
    分布式锁运行时信封。
    """

    model_config = ConfigDict(extra="forbid")

    envelope_kind: Literal["distributed_lock_runtime"] = DISTRIBUTED_LOCK_RUNTIME_KIND
    schema_version: Literal["1.0"] = DISTRIBUTED_LOCK_SCHEMA_VERSION
    header: DistributedLockRuntimeHeader
    detail: DistributedLockRuntimeDetailUnion

    @model_validator(mode="after")
    def validate_lock_runtime_contract(self) -> DistributedLockRuntimeEnvelope:
        """
        校验分布式锁公共头与扩展字段一致。
        """

        if self.schema_version != self.header.schema_version:
            raise ValueError("分布式锁 envelope schema_version 必须与 header 一致。")
        if self.header.schema_version != self.detail.schema_version:
            raise ValueError("分布式锁 header schema_version 必须与 detail 一致。")
        return self


class DistributedLockRequest(BaseModel):
    """
    分布式锁获取请求。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["distributed_lock_request"] = DISTRIBUTED_LOCK_REQUEST_KIND
    schema_version: Literal["1.0"] = DISTRIBUTED_LOCK_SCHEMA_VERSION
    namespace: str = Field(min_length=DISTRIBUTED_LOCK_NAMESPACE_MINIMUM_LENGTH)
    key_digest: str = Field(min_length=DISTRIBUTED_LOCK_KEY_DIGEST_MINIMUM_LENGTH)
    owner: str = Field(min_length=DISTRIBUTED_LOCK_OWNER_MINIMUM_LENGTH)
    lease_seconds: int = Field(ge=DISTRIBUTED_LOCK_TTL_MINIMUM_SECONDS)
    wait_seconds: int = Field(ge=DISTRIBUTED_LOCK_WAIT_MINIMUM_SECONDS)


class DistributedLockLease(BaseModel):
    """
    分布式锁租约。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["distributed_lock_lease"] = DISTRIBUTED_LOCK_LEASE_KIND
    schema_version: Literal["1.0"] = DISTRIBUTED_LOCK_SCHEMA_VERSION
    namespace: str
    key_digest: str
    owner: str
    lock_key: str
    lease_seconds: int = Field(ge=DISTRIBUTED_LOCK_TTL_MINIMUM_SECONDS)
    expires_at_epoch: int = Field(ge=DISTRIBUTED_LOCK_EXPIRES_AT_MINIMUM)
    acquired: bool
    released: bool = False
