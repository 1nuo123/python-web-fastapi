"""管理员用户 HTTP 契约。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from src.api.endpoint_admin_identity.contract_admin_identity_common import (
    ADMIN_IDENTITY_DISABLE_REASON_MAXIMUM_LENGTH,
    ADMIN_IDENTITY_DISABLED_STATUS,
    ADMIN_IDENTITY_ENABLED_STATUS,
    ADMIN_IDENTITY_GRANT_CONFIRMATION_MAXIMUM_LENGTH,
    ADMIN_IDENTITY_PASSWORD_MINIMUM_LENGTH,
    ADMIN_IDENTITY_SCHEMA_VERSION,
    ADMIN_IDENTITY_SUBJECT_ID_MAXIMUM_LENGTH,
    ADMIN_IDENTITY_TEXT_MINIMUM_LENGTH,
    ADMIN_IDENTITY_USERNAME_MAXIMUM_LENGTH,
    ADMIN_USER_CREATE_KIND,
    ADMIN_USER_DISABLE_KIND,
    ADMIN_USER_ENABLE_KIND,
    ADMIN_USER_LIST_KIND,
    ADMIN_USER_PASSWORD_RESET_KIND,
    ADMIN_USER_PAYLOAD_KIND,
    ADMIN_USER_ROLE_REPLACE_KIND,
    ADMIN_USER_STATUS_RESULT_KIND,
    ADMIN_USER_UPDATE_KIND,
)
from src.application.ports.admin_identity_port import (
    ADMIN_IDENTITY_QUERY_LIMIT_MAXIMUM,
    ADMIN_IDENTITY_QUERY_LIMIT_MINIMUM,
    ADMIN_IDENTITY_QUERY_OFFSET_MINIMUM,
    AdminIdentityDeleteResult,
    AdminUserPage,
    AdminUserSnapshot,
)


class AdminUserPayload(BaseModel):
    """
    管理员用户响应载荷。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["admin_user"] = ADMIN_USER_PAYLOAD_KIND
    schema_version: Literal["1.0"] = ADMIN_IDENTITY_SCHEMA_VERSION
    subject_id: str
    username: str
    is_active: bool
    role_keys: list[str]

    @classmethod
    def from_snapshot(cls, snapshot: AdminUserSnapshot) -> AdminUserPayload:
        """
        从用户快照构建响应载荷。
        """

        return cls(
            subject_id=snapshot.subject_id,
            username=snapshot.username,
            is_active=snapshot.is_active,
            role_keys=snapshot.role_keys,
        )


class AdminUserListPayload(BaseModel):
    """
    管理员用户列表载荷。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["admin_user_list"] = ADMIN_USER_LIST_KIND
    schema_version: Literal["1.0"] = ADMIN_IDENTITY_SCHEMA_VERSION
    users: list[AdminUserPayload]
    page_size: int = Field(
        ge=ADMIN_IDENTITY_QUERY_LIMIT_MINIMUM,
        le=ADMIN_IDENTITY_QUERY_LIMIT_MAXIMUM,
    )
    offset: int = Field(ge=ADMIN_IDENTITY_QUERY_OFFSET_MINIMUM)
    total: int = Field(ge=ADMIN_IDENTITY_QUERY_OFFSET_MINIMUM)

    @classmethod
    def from_page(cls, page: AdminUserPage) -> AdminUserListPayload:
        """
        从用户分页结果构建响应载荷。
        """

        return cls(
            users=[AdminUserPayload.from_snapshot(snapshot) for snapshot in page.users],
            page_size=page.page_size,
            offset=page.offset,
            total=page.total,
        )


class AdminUserCreateRequest(BaseModel):
    """
    管理员用户创建请求。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["admin_user_create"] = ADMIN_USER_CREATE_KIND
    schema_version: Literal["1.0"] = ADMIN_IDENTITY_SCHEMA_VERSION
    username: str = Field(
        min_length=ADMIN_IDENTITY_TEXT_MINIMUM_LENGTH,
        max_length=ADMIN_IDENTITY_USERNAME_MAXIMUM_LENGTH,
    )
    password: SecretStr = Field(min_length=ADMIN_IDENTITY_PASSWORD_MINIMUM_LENGTH)
    role_keys: list[str] = Field(default_factory=list)
    subject_id: str | None = Field(
        default=None,
        max_length=ADMIN_IDENTITY_SUBJECT_ID_MAXIMUM_LENGTH,
    )


class AdminUserUpdateRequest(BaseModel):
    """
    管理员用户更新请求。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["admin_user_update"] = ADMIN_USER_UPDATE_KIND
    schema_version: Literal["1.0"] = ADMIN_IDENTITY_SCHEMA_VERSION
    username: str | None = Field(
        default=None,
        min_length=ADMIN_IDENTITY_TEXT_MINIMUM_LENGTH,
        max_length=ADMIN_IDENTITY_USERNAME_MAXIMUM_LENGTH,
    )


class AdminUserPasswordResetRequest(BaseModel):
    """
    管理员用户密码重置请求。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["admin_user_password_reset"] = ADMIN_USER_PASSWORD_RESET_KIND
    schema_version: Literal["1.0"] = ADMIN_IDENTITY_SCHEMA_VERSION
    password: SecretStr = Field(min_length=ADMIN_IDENTITY_PASSWORD_MINIMUM_LENGTH)


class AdminUserRoleReplaceRequest(BaseModel):
    """
    管理员用户角色替换请求。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["admin_user_role_replace"] = ADMIN_USER_ROLE_REPLACE_KIND
    schema_version: Literal["1.0"] = ADMIN_IDENTITY_SCHEMA_VERSION
    role_keys: list[str] = Field(default_factory=list)
    confirmation: str = Field(
        min_length=ADMIN_IDENTITY_TEXT_MINIMUM_LENGTH,
        max_length=ADMIN_IDENTITY_GRANT_CONFIRMATION_MAXIMUM_LENGTH,
    )


class AdminUserDisableRequest(BaseModel):
    """
    管理员用户停用请求。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["admin_user_disable"] = ADMIN_USER_DISABLE_KIND
    schema_version: Literal["1.0"] = ADMIN_IDENTITY_SCHEMA_VERSION
    reason: str = Field(
        min_length=ADMIN_IDENTITY_TEXT_MINIMUM_LENGTH,
        max_length=ADMIN_IDENTITY_DISABLE_REASON_MAXIMUM_LENGTH,
    )


class AdminUserEnableRequest(BaseModel):
    """
    管理员用户启用请求。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["admin_user_enable"] = ADMIN_USER_ENABLE_KIND
    schema_version: Literal["1.0"] = ADMIN_IDENTITY_SCHEMA_VERSION
    reason: str | None = Field(
        default=None,
        max_length=ADMIN_IDENTITY_DISABLE_REASON_MAXIMUM_LENGTH,
    )


class AdminUserStatusResultPayload(BaseModel):
    """
    管理员用户状态变更结果载荷。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["admin_user_status_result"] = ADMIN_USER_STATUS_RESULT_KIND
    schema_version: Literal["1.0"] = ADMIN_IDENTITY_SCHEMA_VERSION
    subject_id: str
    status: Literal["disabled", "enabled"]
    is_active: bool
    reason: str | None = None

    @classmethod
    def from_disabled_result(
        cls,
        result: AdminIdentityDeleteResult,
    ) -> AdminUserStatusResultPayload:
        """
        从停用结果构建用户状态载荷。
        """

        return cls(
            subject_id=result.target_id,
            status=ADMIN_IDENTITY_DISABLED_STATUS,
            is_active=False,
            reason=result.reason,
        )

    @classmethod
    def from_enabled_snapshot(
        cls,
        snapshot: AdminUserSnapshot,
        *,
        reason: str | None,
    ) -> AdminUserStatusResultPayload:
        """
        从启用后的用户快照构建用户状态载荷。
        """

        return cls(
            subject_id=snapshot.subject_id,
            status=ADMIN_IDENTITY_ENABLED_STATUS,
            is_active=snapshot.is_active,
            reason=reason,
        )
