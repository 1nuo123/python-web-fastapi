"""
业务后台审计 HTTP 契约。
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.application.ports.admin_audit_query_port import (
    ADMIN_AUDIT_OFFSET_MINIMUM,
    ADMIN_AUDIT_PAGE_SIZE_DEFAULT,
    ADMIN_AUDIT_PAGE_SIZE_MAXIMUM,
    ADMIN_AUDIT_PAGE_SIZE_MINIMUM,
    AdminAuditAction,
    AdminAuditEventPage,
    AdminAuditEventSnapshot,
    AdminAuditQuery,
    AdminAuditResult,
)

ADMIN_AUDIT_SCHEMA_VERSION: Final = "1.0"
ADMIN_AUDIT_EVENT_KIND: Final = "admin_audit_event"
ADMIN_AUDIT_EVENT_LIST_KIND: Final = "admin_audit_event_list"
ADMIN_AUDIT_TARGET_MINIMUM_LENGTH = 1


class AdminAuditOperationName(StrEnum):
    """
    业务审计操作名称枚举。
    """

    EVENT_LIST = "event_list"


class AdminAuditPayloadKind(StrEnum):
    """
    业务审计载荷类型枚举。
    """

    EVENT = ADMIN_AUDIT_EVENT_KIND
    EVENT_LIST = ADMIN_AUDIT_EVENT_LIST_KIND


class AdminAuditHeader(BaseModel):
    """
    业务审计公共头。
    """

    model_config = ConfigDict(extra="forbid")

    kind: AdminAuditPayloadKind
    schema_version: Literal["1.0"] = ADMIN_AUDIT_SCHEMA_VERSION
    operation_name: AdminAuditOperationName


class AdminAuditEventPayload(BaseModel):
    """
    业务审计事件载荷。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["admin_audit_event"] = ADMIN_AUDIT_EVENT_KIND
    schema_version: Literal["1.0"] = ADMIN_AUDIT_SCHEMA_VERSION
    event_id: str
    action: AdminAuditAction
    actor_subject_id: str
    target_kind: str
    target_id: str
    result: AdminAuditResult
    occurred_at: datetime
    summary: str

    @classmethod
    def from_snapshot(
        cls,
        snapshot: AdminAuditEventSnapshot,
    ) -> AdminAuditEventPayload:
        """
        从业务审计快照构建事件载荷。

        :param snapshot: 业务审计事件快照。
        :type snapshot: AdminAuditEventSnapshot
        :returns: 业务审计事件载荷。
        :rtype: AdminAuditEventPayload
        """

        return cls(
            event_id=snapshot.event_id,
            action=snapshot.action,
            actor_subject_id=snapshot.actor_subject_id,
            target_kind=snapshot.target_kind,
            target_id=snapshot.target_id,
            result=snapshot.result,
            occurred_at=snapshot.occurred_at,
            summary=snapshot.summary,
        )


class AdminAuditEventListPayload(BaseModel):
    """
    业务审计事件列表载荷。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["admin_audit_event_list"] = ADMIN_AUDIT_EVENT_LIST_KIND
    schema_version: Literal["1.0"] = ADMIN_AUDIT_SCHEMA_VERSION
    events: list[AdminAuditEventPayload]
    page_size: int = Field(
        default=ADMIN_AUDIT_PAGE_SIZE_DEFAULT,
        ge=ADMIN_AUDIT_PAGE_SIZE_MINIMUM,
        le=ADMIN_AUDIT_PAGE_SIZE_MAXIMUM,
    )
    offset: int = Field(default=ADMIN_AUDIT_OFFSET_MINIMUM, ge=ADMIN_AUDIT_OFFSET_MINIMUM)
    total: int = Field(ge=ADMIN_AUDIT_OFFSET_MINIMUM)

    @classmethod
    def from_page(cls, page: AdminAuditEventPage) -> AdminAuditEventListPayload:
        """
        从业务审计分页结果构建列表载荷。

        :param page: 业务审计分页结果。
        :type page: AdminAuditEventPage
        :returns: 业务审计列表载荷。
        :rtype: AdminAuditEventListPayload
        """

        return cls(
            events=[AdminAuditEventPayload.from_snapshot(snapshot) for snapshot in page.events],
            page_size=page.page_size,
            offset=page.offset,
            total=page.total,
        )


class AdminAuditQueryPayload(BaseModel):
    """
    业务审计查询载荷。
    """

    model_config = ConfigDict(extra="forbid")

    actor_subject_id: str | None = None
    action: AdminAuditAction | None = None
    target_kind: str | None = Field(
        default=None,
        min_length=ADMIN_AUDIT_TARGET_MINIMUM_LENGTH,
    )
    target_id: str | None = Field(
        default=None,
        min_length=ADMIN_AUDIT_TARGET_MINIMUM_LENGTH,
    )
    occurred_from: datetime | None = None
    occurred_to: datetime | None = None
    page_size: int = Field(
        default=ADMIN_AUDIT_PAGE_SIZE_DEFAULT,
        ge=ADMIN_AUDIT_PAGE_SIZE_MINIMUM,
        le=ADMIN_AUDIT_PAGE_SIZE_MAXIMUM,
    )
    offset: int = Field(default=ADMIN_AUDIT_OFFSET_MINIMUM, ge=ADMIN_AUDIT_OFFSET_MINIMUM)

    def to_query(self) -> AdminAuditQuery:
        """
        转换为应用层查询对象。

        :returns: 应用层业务审计查询对象。
        :rtype: AdminAuditQuery
        """

        return AdminAuditQuery(
            actor_subject_id=self.actor_subject_id,
            action=self.action,
            target_kind=self.target_kind,
            target_id=self.target_id,
            occurred_from=self.occurred_from,
            occurred_to=self.occurred_to,
            page_size=self.page_size,
            offset=self.offset,
        )


AdminAuditDetailUnion = Annotated[
    AdminAuditEventPayload | AdminAuditEventListPayload,
    Field(discriminator="kind"),
]


class AdminAuditEnvelope(BaseModel):
    """
    业务审计信封。
    """

    model_config = ConfigDict(extra="forbid")

    header: AdminAuditHeader
    detail: AdminAuditDetailUnion

    @model_validator(mode="after")
    def validate_detail_contract(self) -> AdminAuditEnvelope:
        """
        校验业务审计公共头与扩展字段一致。

        :returns: 当前信封。
        :rtype: AdminAuditEnvelope
        """

        if self.header.kind.value != self.detail.kind:
            raise ValueError("业务审计 header.kind 必须与 detail.kind 一致。")
        if self.header.schema_version != self.detail.schema_version:
            raise ValueError("业务审计 schema_version 必须一致。")
        return self
