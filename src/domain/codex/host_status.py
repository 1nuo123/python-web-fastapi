"""Codex 控制面稳定状态枚举。"""

from enum import StrEnum


class CodexHostStatus(StrEnum):
    ENROLLING = "enrolling"
    ONLINE = "online"
    OFFLINE = "offline"
    INCOMPATIBLE = "incompatible"
    REVOKED = "revoked"


class CodexThreadStatus(StrEnum):
    IDLE = "idle"
    ACTIVE = "active"
    INTERRUPTED = "interrupted"
    UNKNOWN = "unknown"
    ARCHIVED = "archived"


class CodexOperationStatus(StrEnum):
    PENDING = "pending"
    DISPATCHED = "dispatched"
    ACKNOWLEDGED = "acknowledged"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


class CodexApprovalState(StrEnum):
    PENDING = "pending"
    CLAIMED = "claimed"
    APPLIED = "applied"
    DELIVERY_FAILED = "delivery_failed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
