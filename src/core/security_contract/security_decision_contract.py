"""
安全决策契约模块。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict

from src.core.security_contract.security_event_contract import SecurityEventEnvelope

SECURITY_DECISION_SCHEMA_VERSION: Final = "1.0"
SECURITY_DECISION_KIND: Final = "security_decision"


class SecurityAction(StrEnum):
    """
    安全处置动作枚举。
    """

    ALLOW = "allow"
    DENY = "deny"
    THROTTLE = "throttle"
    RECORD_ONLY = "record_only"
    RETURN_429 = "return_429"


class SecurityDecisionEnvelope(BaseModel):
    """
    安全决策信封。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["security_decision"] = SECURITY_DECISION_KIND
    schema_version: Literal["1.0"] = SECURITY_DECISION_SCHEMA_VERSION
    action: SecurityAction
    policy_name: str
    reason_code: str
    retry_after_seconds: int | None = None
    security_event: SecurityEventEnvelope | None = None
