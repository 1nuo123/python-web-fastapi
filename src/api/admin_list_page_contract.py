"""
业务后台分页 HTTP 契约。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.application.ports.admin_identity_port import (
    ADMIN_IDENTITY_QUERY_LIMIT_DEFAULT,
    ADMIN_IDENTITY_QUERY_LIMIT_MAXIMUM,
    ADMIN_IDENTITY_QUERY_LIMIT_MINIMUM,
    ADMIN_IDENTITY_QUERY_OFFSET_MINIMUM,
)

ADMIN_LIST_PAGE_SCHEMA_VERSION: Final = "1.0"
ADMIN_LIST_PAGE_QUERY_KIND: Final = "admin_list_page_query"
ADMIN_LIST_PAGE_PAYLOAD_KIND: Final = "admin_list_page_payload"


class AdminListPageOperationName(StrEnum):
    """
    业务后台分页操作名称枚举。
    """

    QUERY = "page_query"
    PAYLOAD = "page_payload"


class AdminListPagePayloadKind(StrEnum):
    """
    业务后台分页载荷类型枚举。
    """

    QUERY = ADMIN_LIST_PAGE_QUERY_KIND
    PAYLOAD = ADMIN_LIST_PAGE_PAYLOAD_KIND


class AdminListPageHeader(BaseModel):
    """
    业务后台分页公共头。
    """

    model_config = ConfigDict(extra="forbid")

    kind: AdminListPagePayloadKind
    schema_version: Literal["1.0"] = ADMIN_LIST_PAGE_SCHEMA_VERSION
    operation_name: AdminListPageOperationName


class AdminListPageQuery(BaseModel):
    """
    业务后台列表分页查询扩展字段。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["admin_list_page_query"] = ADMIN_LIST_PAGE_QUERY_KIND
    schema_version: Literal["1.0"] = ADMIN_LIST_PAGE_SCHEMA_VERSION
    page_size: int = Field(
        default=ADMIN_IDENTITY_QUERY_LIMIT_DEFAULT,
        ge=ADMIN_IDENTITY_QUERY_LIMIT_MINIMUM,
        le=ADMIN_IDENTITY_QUERY_LIMIT_MAXIMUM,
    )
    offset: int = Field(
        default=ADMIN_IDENTITY_QUERY_OFFSET_MINIMUM,
        ge=ADMIN_IDENTITY_QUERY_OFFSET_MINIMUM,
    )


class AdminListPagePayload(BaseModel):
    """
    业务后台列表分页响应扩展字段。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["admin_list_page_payload"] = ADMIN_LIST_PAGE_PAYLOAD_KIND
    schema_version: Literal["1.0"] = ADMIN_LIST_PAGE_SCHEMA_VERSION
    page_size: int = Field(
        ge=ADMIN_IDENTITY_QUERY_LIMIT_MINIMUM,
        le=ADMIN_IDENTITY_QUERY_LIMIT_MAXIMUM,
    )
    items: list[str] = Field(default_factory=list)
    offset: int = Field(ge=ADMIN_IDENTITY_QUERY_OFFSET_MINIMUM)
    total: int = Field(ge=ADMIN_IDENTITY_QUERY_OFFSET_MINIMUM)
    next_cursor: str | None = None


AdminListPageDetailUnion = Annotated[
    AdminListPageQuery | AdminListPagePayload,
    Field(discriminator="kind"),
]


class AdminListPageEnvelope(BaseModel):
    """
    业务后台分页信封。
    """

    model_config = ConfigDict(extra="forbid")

    header: AdminListPageHeader
    detail: AdminListPageDetailUnion

    @model_validator(mode="after")
    def validate_detail_contract(self) -> AdminListPageEnvelope:
        """
        校验业务后台分页公共头与扩展字段一致。

        :returns: 当前信封。
        :rtype: AdminListPageEnvelope
        :raises ValueError: 当公共头与扩展字段不一致时抛出。
        """

        if self.header.kind.value != self.detail.kind:
            raise ValueError("业务后台分页 header.kind 必须与 detail.kind 一致。")
        if self.header.schema_version != self.detail.schema_version:
            raise ValueError("业务后台分页 schema_version 必须一致。")
        return self
