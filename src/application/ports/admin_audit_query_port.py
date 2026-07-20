"""
业务后台审计查询端口。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

ADMIN_AUDIT_PAGE_SIZE_DEFAULT = 50
ADMIN_AUDIT_PAGE_SIZE_MINIMUM = 1
ADMIN_AUDIT_PAGE_SIZE_MAXIMUM = 200
ADMIN_AUDIT_OFFSET_MINIMUM = 0


class AdminAuditAction(StrEnum):
    """
    业务审计动作枚举。
    """

    USER_CREATED = "user_created"
    USER_UPDATED = "user_updated"
    USER_DISABLED = "user_disabled"
    USER_ENABLED = "user_enabled"
    PASSWORD_RESET = "password_reset"
    ROLE_ASSIGNED = "role_assigned"


class AdminAuditResult(StrEnum):
    """
    业务审计结果枚举。
    """

    SUCCESS = "success"
    FAILED = "failed"


@dataclass(slots=True)
class AdminAuditQuery:
    """
    业务审计查询。
    """

    actor_subject_id: str | None
    action: AdminAuditAction | None
    target_kind: str | None
    target_id: str | None
    occurred_from: datetime | None
    occurred_to: datetime | None
    page_size: int
    offset: int


@dataclass(slots=True)
class AdminAuditEventSnapshot:
    """
    业务审计事件快照。
    """

    event_id: str
    action: AdminAuditAction
    actor_subject_id: str
    target_kind: str
    target_id: str
    result: AdminAuditResult
    occurred_at: datetime
    summary: str


@dataclass(slots=True)
class AdminAuditEventPage:
    """
    业务审计事件分页结果。
    """

    events: list[AdminAuditEventSnapshot]
    page_size: int
    offset: int
    total: int


class AdminAuditQueryPort(Protocol):
    """
    业务审计查询端口。
    """

    def list_admin_audit_events(
        self,
        query: AdminAuditQuery,
    ) -> AdminAuditEventPage:
        """
        查询业务审计事件。
        """
