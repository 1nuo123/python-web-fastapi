"""管理员 scope HTTP 契约。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.api.endpoint_admin_identity.contract_admin_identity_common import (
    ADMIN_IDENTITY_SCHEMA_VERSION,
    ADMIN_IDENTITY_SCOPE_CODE_MAXIMUM_LENGTH,
    ADMIN_IDENTITY_TEXT_MINIMUM_LENGTH,
    ADMIN_SCOPE_CREATE_KIND,
    ADMIN_SCOPE_LIST_KIND,
    ADMIN_SCOPE_PAYLOAD_KIND,
    ADMIN_SCOPE_UPDATE_KIND,
)
from src.application.ports.admin_identity_port import (
    AdminScopeKind,
    AdminScopeSnapshot,
)


class AdminScopePayload(BaseModel):
    """
    管理员 scope 响应载荷。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["admin_scope"] = ADMIN_SCOPE_PAYLOAD_KIND
    schema_version: Literal["1.0"] = ADMIN_IDENTITY_SCHEMA_VERSION
    scope_code: str
    scope_name: str
    description: str | None
    scope_kind: AdminScopeKind
    enabled: bool

    @classmethod
    def from_snapshot(cls, snapshot: AdminScopeSnapshot) -> AdminScopePayload:
        """
        从 scope 快照构建响应载荷。
        """

        return cls(
            scope_code=snapshot.scope_code,
            scope_name=snapshot.scope_name,
            description=snapshot.description,
            scope_kind=snapshot.scope_kind,
            enabled=snapshot.enabled,
        )


class AdminScopeListPayload(BaseModel):
    """
    管理员 scope 列表载荷。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["admin_scope_list"] = ADMIN_SCOPE_LIST_KIND
    schema_version: Literal["1.0"] = ADMIN_IDENTITY_SCHEMA_VERSION
    scopes: list[AdminScopePayload]

    @classmethod
    def from_snapshots(
        cls,
        snapshots: list[AdminScopeSnapshot],
    ) -> AdminScopeListPayload:
        """
        从 scope 快照列表构建响应载荷。
        """

        return cls(scopes=[AdminScopePayload.from_snapshot(snapshot) for snapshot in snapshots])


class AdminScopeCreateRequest(BaseModel):
    """
    管理员 scope 创建请求。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["admin_scope_create"] = ADMIN_SCOPE_CREATE_KIND
    schema_version: Literal["1.0"] = ADMIN_IDENTITY_SCHEMA_VERSION
    scope_code: str = Field(
        min_length=ADMIN_IDENTITY_TEXT_MINIMUM_LENGTH,
        max_length=ADMIN_IDENTITY_SCOPE_CODE_MAXIMUM_LENGTH,
    )
    scope_name: str = Field(min_length=ADMIN_IDENTITY_TEXT_MINIMUM_LENGTH)
    description: str | None = None
    enabled: bool = True


class AdminScopeUpdateRequest(BaseModel):
    """
    管理员 scope 更新请求。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["admin_scope_update"] = ADMIN_SCOPE_UPDATE_KIND
    schema_version: Literal["1.0"] = ADMIN_IDENTITY_SCHEMA_VERSION
    scope_name: str | None = Field(
        default=None,
        min_length=ADMIN_IDENTITY_TEXT_MINIMUM_LENGTH,
    )
    description: str | None = None
    enabled: bool | None = None
