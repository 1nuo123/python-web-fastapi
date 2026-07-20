"""管理员角色 HTTP 契约。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.api.endpoint_admin_identity.contract_admin_identity_common import (
    ADMIN_BUSINESS_ROLE_LIST_KIND,
    ADMIN_BUSINESS_ROLE_PAYLOAD_KIND,
    ADMIN_IDENTITY_GRANT_CONFIRMATION_MAXIMUM_LENGTH,
    ADMIN_IDENTITY_ROLE_KEY_MAXIMUM_LENGTH,
    ADMIN_IDENTITY_SCHEMA_VERSION,
    ADMIN_IDENTITY_TEXT_MINIMUM_LENGTH,
    ADMIN_ROLE_CREATE_KIND,
    ADMIN_ROLE_LIST_KIND,
    ADMIN_ROLE_PAYLOAD_KIND,
    ADMIN_ROLE_SCOPE_REPLACE_KIND,
    ADMIN_ROLE_UPDATE_KIND,
)
from src.application.ports.admin_identity_port import (
    ADMIN_IDENTITY_QUERY_LIMIT_MAXIMUM,
    ADMIN_IDENTITY_QUERY_LIMIT_MINIMUM,
    ADMIN_IDENTITY_QUERY_OFFSET_MINIMUM,
    AdminRolePage,
    AdminRoleSnapshot,
    BusinessAdminRoleKey,
)


class AdminRolePayload(BaseModel):
    """
    管理员角色响应载荷。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["admin_role"] = ADMIN_ROLE_PAYLOAD_KIND
    schema_version: Literal["1.0"] = ADMIN_IDENTITY_SCHEMA_VERSION
    role_key: str
    role_name: str
    scope_codes: list[str]
    user_count: int = Field(ge=0)

    @classmethod
    def from_snapshot(cls, snapshot: AdminRoleSnapshot) -> AdminRolePayload:
        """
        从角色快照构建响应载荷。
        """

        return cls(
            role_key=snapshot.role_key,
            role_name=snapshot.role_name,
            scope_codes=snapshot.scope_codes,
            user_count=snapshot.user_count,
        )


class AdminRoleListPayload(BaseModel):
    """
    管理员角色分页列表载荷。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["admin_role_list"] = ADMIN_ROLE_LIST_KIND
    schema_version: Literal["1.0"] = ADMIN_IDENTITY_SCHEMA_VERSION
    roles: list[AdminRolePayload]
    page_size: int = Field(
        ge=ADMIN_IDENTITY_QUERY_LIMIT_MINIMUM,
        le=ADMIN_IDENTITY_QUERY_LIMIT_MAXIMUM,
    )
    offset: int = Field(ge=ADMIN_IDENTITY_QUERY_OFFSET_MINIMUM)
    total: int = Field(ge=ADMIN_IDENTITY_QUERY_OFFSET_MINIMUM)

    @classmethod
    def from_page(cls, page: AdminRolePage) -> AdminRoleListPayload:
        """
        从角色分页结果构建响应载荷。
        """

        return cls(
            roles=[AdminRolePayload.from_snapshot(snapshot) for snapshot in page.roles],
            page_size=page.page_size,
            offset=page.offset,
            total=page.total,
        )


class AdminBusinessRolePayload(BaseModel):
    """
    业务后台可分配角色载荷。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["admin_business_role"] = ADMIN_BUSINESS_ROLE_PAYLOAD_KIND
    schema_version: Literal["1.0"] = ADMIN_IDENTITY_SCHEMA_VERSION
    role_key: BusinessAdminRoleKey
    role_name: str

    @classmethod
    def from_snapshot(cls, snapshot: AdminRoleSnapshot) -> AdminBusinessRolePayload:
        """
        从角色快照构建业务角色载荷。
        """

        return cls(
            role_key=BusinessAdminRoleKey(snapshot.role_key),
            role_name=snapshot.role_name,
        )


class AdminBusinessRoleListPayload(BaseModel):
    """
    业务后台可分配角色分页载荷。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["admin_business_role_list"] = ADMIN_BUSINESS_ROLE_LIST_KIND
    schema_version: Literal["1.0"] = ADMIN_IDENTITY_SCHEMA_VERSION
    roles: list[AdminBusinessRolePayload]
    page_size: int = Field(
        ge=ADMIN_IDENTITY_QUERY_LIMIT_MINIMUM,
        le=ADMIN_IDENTITY_QUERY_LIMIT_MAXIMUM,
    )
    offset: int = Field(ge=ADMIN_IDENTITY_QUERY_OFFSET_MINIMUM)
    total: int = Field(ge=ADMIN_IDENTITY_QUERY_OFFSET_MINIMUM)

    @classmethod
    def from_page(cls, page: AdminRolePage) -> AdminBusinessRoleListPayload:
        """
        从角色分页结果构建业务角色列表载荷。
        """

        return cls(
            roles=[AdminBusinessRolePayload.from_snapshot(snapshot) for snapshot in page.roles],
            page_size=page.page_size,
            offset=page.offset,
            total=page.total,
        )


class AdminRoleCreateRequest(BaseModel):
    """
    管理员角色创建请求。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["admin_role_create"] = ADMIN_ROLE_CREATE_KIND
    schema_version: Literal["1.0"] = ADMIN_IDENTITY_SCHEMA_VERSION
    role_key: str = Field(
        min_length=ADMIN_IDENTITY_TEXT_MINIMUM_LENGTH,
        max_length=ADMIN_IDENTITY_ROLE_KEY_MAXIMUM_LENGTH,
    )
    role_name: str = Field(min_length=ADMIN_IDENTITY_TEXT_MINIMUM_LENGTH)
    scope_codes: list[str] = Field(default_factory=list)
    confirmation: str | None = Field(
        default=None,
        min_length=ADMIN_IDENTITY_TEXT_MINIMUM_LENGTH,
        max_length=ADMIN_IDENTITY_GRANT_CONFIRMATION_MAXIMUM_LENGTH,
    )


class AdminRoleUpdateRequest(BaseModel):
    """
    管理员角色更新请求。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["admin_role_update"] = ADMIN_ROLE_UPDATE_KIND
    schema_version: Literal["1.0"] = ADMIN_IDENTITY_SCHEMA_VERSION
    role_name: str = Field(min_length=ADMIN_IDENTITY_TEXT_MINIMUM_LENGTH)


class AdminRoleScopeReplaceRequest(BaseModel):
    """
    管理员角色 scope 替换请求。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["admin_role_scope_replace"] = ADMIN_ROLE_SCOPE_REPLACE_KIND
    schema_version: Literal["1.0"] = ADMIN_IDENTITY_SCHEMA_VERSION
    scope_codes: list[str] = Field(default_factory=list)
    confirmation: str = Field(
        min_length=ADMIN_IDENTITY_TEXT_MINIMUM_LENGTH,
        max_length=ADMIN_IDENTITY_GRANT_CONFIRMATION_MAXIMUM_LENGTH,
    )
