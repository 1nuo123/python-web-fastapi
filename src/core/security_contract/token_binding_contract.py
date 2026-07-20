"""
Token-IP 绑定契约模块。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

TOKEN_BINDING_SCHEMA_VERSION: Final = "1.0"
TOKEN_BINDING_KIND: Final = "token_binding_policy"
TOKEN_BINDING_TTL_MINIMUM_SECONDS = 1


class TokenBindingMode(StrEnum):
    """
    Token-IP 绑定模式枚举。
    """

    DISABLED = "disabled"
    HIGH_RISK_ONLY = "high_risk_only"


class TokenBindingEnvelope(BaseModel):
    """
    Token-IP 绑定策略信封。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["token_binding_policy"] = TOKEN_BINDING_KIND
    schema_version: Literal["1.0"] = TOKEN_BINDING_SCHEMA_VERSION
    enabled: bool
    mode: TokenBindingMode
    ip_digest_ttl_seconds: int = Field(ge=TOKEN_BINDING_TTL_MINIMUM_SECONDS)
    applicable_paths: list[str] = Field(default_factory=list)
    token_uses: list[str] = Field(default_factory=list)
