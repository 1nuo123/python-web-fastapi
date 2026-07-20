"""
限流策略契约模块。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

RATE_LIMIT_SCHEMA_VERSION: Final = "1.0"
RATE_LIMIT_POLICY_HEADER_KIND: Final = "rate_limit_policy_header"
RATE_LIMIT_POLICY_KIND: Final = "rate_limit_policy"
RATE_LIMIT_POLICY_NAME_MINIMUM_LENGTH = 1
RATE_LIMIT_LIMIT_MINIMUM_VALUE = 1
RATE_LIMIT_WINDOW_MINIMUM_SECONDS = 1
RATE_LIMIT_PATH_MINIMUM_LENGTH = 1
RATE_LIMIT_METHOD_MINIMUM_LENGTH = 1


class RateLimitKeyDimension(StrEnum):
    """
    限流键维度枚举。
    """

    IP_DIGEST = "ip_digest"
    SUBJECT_ID = "subject_id"
    PATH_METHOD = "path_method"
    AUTH_FIELD_DIGEST = "auth_field_digest"


class RateLimitPolicyHeader(BaseModel):
    """
    限流策略公共头。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["rate_limit_policy_header"] = RATE_LIMIT_POLICY_HEADER_KIND
    schema_version: Literal["1.0"] = RATE_LIMIT_SCHEMA_VERSION
    detail_kind: Literal["rate_limit_policy"] = RATE_LIMIT_POLICY_KIND
    policy_name: str = Field(min_length=RATE_LIMIT_POLICY_NAME_MINIMUM_LENGTH)
    enabled: bool


class RateLimitPolicyDetail(BaseModel):
    """
    限流策略扩展字段。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["rate_limit_policy"] = RATE_LIMIT_POLICY_KIND
    schema_version: Literal["1.0"] = RATE_LIMIT_SCHEMA_VERSION
    path: str | None = Field(default=None, min_length=RATE_LIMIT_PATH_MINIMUM_LENGTH)
    method: str | None = Field(default=None, min_length=RATE_LIMIT_METHOD_MINIMUM_LENGTH)
    limit: int = Field(ge=RATE_LIMIT_LIMIT_MINIMUM_VALUE)
    window_seconds: int = Field(ge=RATE_LIMIT_WINDOW_MINIMUM_SECONDS)
    key_dimensions: list[RateLimitKeyDimension] = Field(min_length=1)
    block_when_exceeded: bool = False
    block_seconds: int = Field(
        default=RATE_LIMIT_WINDOW_MINIMUM_SECONDS, ge=RATE_LIMIT_WINDOW_MINIMUM_SECONDS
    )


RateLimitPolicyDetailUnion = Annotated[
    RateLimitPolicyDetail,
    Field(discriminator="kind"),
]


class RateLimitPolicyEnvelope(BaseModel):
    """
    限流策略信封。
    """

    model_config = ConfigDict(extra="forbid")

    header: RateLimitPolicyHeader
    detail: RateLimitPolicyDetailUnion

    @model_validator(mode="after")
    def validate_rate_limit_policy(self) -> RateLimitPolicyEnvelope:
        """
        校验限流策略公共头与扩展字段一致。
        """

        if self.header.detail_kind != self.detail.kind:
            raise ValueError("限流策略 header.detail_kind 必须与 detail.kind 一致。")
        if self.header.schema_version != self.detail.schema_version:
            raise ValueError("限流策略 header.schema_version 必须与 detail 一致。")
        return self
