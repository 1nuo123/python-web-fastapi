"""管理员身份 HTTP 信封契约。"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.api.endpoint_admin_identity.contract_admin_identity_common import (
    ADMIN_IDENTITY_HEADER_KIND_MISMATCH_MESSAGE,
    ADMIN_IDENTITY_OPERATION_DETAIL_KINDS,
    ADMIN_IDENTITY_OPERATION_KIND_MISMATCH_MESSAGE,
    ADMIN_IDENTITY_SCHEMA_VERSION_MISMATCH_MESSAGE,
    AdminIdentityDeleteResultPayload,
    AdminIdentityHeader,
)
from src.api.endpoint_admin_identity.contract_admin_role import (
    AdminBusinessRoleListPayload,
    AdminBusinessRolePayload,
    AdminRoleCreateRequest,
    AdminRoleListPayload,
    AdminRolePayload,
    AdminRoleScopeReplaceRequest,
    AdminRoleUpdateRequest,
)
from src.api.endpoint_admin_identity.contract_admin_scope import (
    AdminScopeCreateRequest,
    AdminScopeListPayload,
    AdminScopePayload,
    AdminScopeUpdateRequest,
)
from src.api.endpoint_admin_identity.contract_admin_user import (
    AdminUserCreateRequest,
    AdminUserDisableRequest,
    AdminUserEnableRequest,
    AdminUserListPayload,
    AdminUserPasswordResetRequest,
    AdminUserPayload,
    AdminUserRoleReplaceRequest,
    AdminUserScopeReplaceRequest,
    AdminUserStatusResultPayload,
    AdminUserUpdateRequest,
)

AdminIdentityDetailUnion = Annotated[
    AdminScopePayload
    | AdminScopeListPayload
    | AdminScopeCreateRequest
    | AdminScopeUpdateRequest
    | AdminRolePayload
    | AdminRoleListPayload
    | AdminRoleCreateRequest
    | AdminRoleUpdateRequest
    | AdminRoleScopeReplaceRequest
    | AdminBusinessRolePayload
    | AdminBusinessRoleListPayload
    | AdminUserPayload
    | AdminUserListPayload
    | AdminUserCreateRequest
    | AdminUserUpdateRequest
    | AdminUserPasswordResetRequest
    | AdminUserRoleReplaceRequest
    | AdminUserScopeReplaceRequest
    | AdminUserDisableRequest
    | AdminUserEnableRequest
    | AdminUserStatusResultPayload
    | AdminIdentityDeleteResultPayload,
    Field(discriminator="kind"),
]


class AdminIdentityEnvelope(BaseModel):
    """
    管理员身份信封。
    """

    model_config = ConfigDict(extra="forbid")

    header: AdminIdentityHeader
    detail: AdminIdentityDetailUnion

    @model_validator(mode="after")
    def validate_detail_contract(self) -> AdminIdentityEnvelope:
        """
        校验公共头与扩展字段一致。

        :returns: 当前信封。
        :rtype: AdminIdentityEnvelope
        """

        if self.header.kind.value != self.detail.kind:
            raise ValueError(ADMIN_IDENTITY_HEADER_KIND_MISMATCH_MESSAGE)
        if self.header.schema_version != self.detail.schema_version:
            raise ValueError(ADMIN_IDENTITY_SCHEMA_VERSION_MISMATCH_MESSAGE)
        if (
            self.header.kind
            not in ADMIN_IDENTITY_OPERATION_DETAIL_KINDS[self.header.operation_name]
        ):
            raise ValueError(ADMIN_IDENTITY_OPERATION_KIND_MISMATCH_MESSAGE)
        return self
