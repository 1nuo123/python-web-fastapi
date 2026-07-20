"""
密钥轮转策略契约模块。
"""

from __future__ import annotations

from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

KEY_ROTATION_SCHEMA_VERSION: Final = "1.0"
KEY_ROTATION_POLICY_KIND: Final = "key_rotation_policy"
KEY_ROTATION_INTERVAL_MINIMUM_SECONDS = 1
KEY_ROTATION_ACTIVE_KEY_COUNT_MINIMUM = 1
KEY_ROTATION_COMPATIBILITY_WINDOW_MINIMUM_SECONDS = 1


class KeyRotationPolicyEnvelope(BaseModel):
    """
    密钥轮转策略信封。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["key_rotation_policy"] = KEY_ROTATION_POLICY_KIND
    schema_version: Literal["1.0"] = KEY_ROTATION_SCHEMA_VERSION
    enabled: bool
    rotation_interval_seconds: int = Field(ge=KEY_ROTATION_INTERVAL_MINIMUM_SECONDS)
    active_key_count: int = Field(ge=KEY_ROTATION_ACTIVE_KEY_COUNT_MINIMUM)
    compatibility_window_seconds: int = Field(
        default=KEY_ROTATION_COMPATIBILITY_WINDOW_MINIMUM_SECONDS,
        ge=KEY_ROTATION_COMPATIBILITY_WINDOW_MINIMUM_SECONDS,
    )
