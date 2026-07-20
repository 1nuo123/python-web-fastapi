"""管理员身份 HTTP 公共契约。"""

from __future__ import annotations

from enum import StrEnum
from typing import Final, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict

from src.application.ports.admin_identity_port import (
    AdminIdentityDeleteResult,
)

ADMIN_IDENTITY_SCHEMA_VERSION: Final = "1.0"

ADMIN_IDENTITY_TEXT_MINIMUM_LENGTH = 1

ADMIN_IDENTITY_SCOPE_CODE_MAXIMUM_LENGTH = 128

ADMIN_IDENTITY_ROLE_KEY_MAXIMUM_LENGTH = 64

ADMIN_IDENTITY_USERNAME_MAXIMUM_LENGTH = 128

ADMIN_IDENTITY_SUBJECT_ID_MAXIMUM_LENGTH = 128

ADMIN_IDENTITY_PASSWORD_MINIMUM_LENGTH = 1

ADMIN_SCOPE_PAYLOAD_KIND: Final = "admin_scope"

ADMIN_SCOPE_LIST_KIND: Final = "admin_scope_list"

ADMIN_SCOPE_CREATE_KIND: Final = "admin_scope_create"

ADMIN_SCOPE_UPDATE_KIND: Final = "admin_scope_update"

ADMIN_SCOPE_DELETE_RESULT_KIND: Final = "admin_scope_delete_result"

ADMIN_ROLE_PAYLOAD_KIND: Final = "admin_role"

ADMIN_ROLE_LIST_KIND: Final = "admin_role_list"

ADMIN_ROLE_CREATE_KIND: Final = "admin_role_create"

ADMIN_ROLE_UPDATE_KIND: Final = "admin_role_update"

ADMIN_ROLE_SCOPE_REPLACE_KIND: Final = "admin_role_scope_replace"

ADMIN_ROLE_DELETE_RESULT_KIND: Final = "admin_role_delete_result"

ADMIN_USER_PAYLOAD_KIND: Final = "admin_user"

ADMIN_USER_LIST_KIND: Final = "admin_user_list"

ADMIN_USER_CREATE_KIND: Final = "admin_user_create"

ADMIN_USER_UPDATE_KIND: Final = "admin_user_update"

ADMIN_USER_PASSWORD_RESET_KIND: Final = "admin_user_password_reset"

ADMIN_USER_ROLE_REPLACE_KIND: Final = "admin_user_role_replace"

ADMIN_USER_DELETE_RESULT_KIND: Final = "admin_user_delete_result"

ADMIN_USER_DISABLE_KIND: Final = "admin_user_disable"

ADMIN_USER_ENABLE_KIND: Final = "admin_user_enable"

ADMIN_USER_STATUS_RESULT_KIND: Final = "admin_user_status_result"

ADMIN_BUSINESS_ROLE_PAYLOAD_KIND: Final = "admin_business_role"

ADMIN_BUSINESS_ROLE_LIST_KIND: Final = "admin_business_role_list"

ADMIN_IDENTITY_DISABLED_STATUS: Final = "disabled"

ADMIN_IDENTITY_ENABLED_STATUS: Final = "enabled"

ADMIN_IDENTITY_DISABLE_REASON_MAXIMUM_LENGTH = 256

ADMIN_IDENTITY_GRANT_CONFIRMATION_PHRASE = "confirm-admin-grant"

ADMIN_IDENTITY_GRANT_CONFIRMATION_MAXIMUM_LENGTH = 64

ADMIN_IDENTITY_GRANT_CONFIRMATION_INVALID_MESSAGE = "高危授权变更必须提供二次确认短语。"

ADMIN_IDENTITY_HEADER_KIND_MISMATCH_MESSAGE = "管理员身份 header.kind 必须与 detail.kind 一致。"

ADMIN_IDENTITY_SCHEMA_VERSION_MISMATCH_MESSAGE = "管理员身份 schema_version 必须一致。"

ADMIN_IDENTITY_OPERATION_KIND_MISMATCH_MESSAGE = "管理员身份 operation_name 与 detail.kind 不匹配。"


class AdminIdentityOperationName(StrEnum):
    """
    管理员身份操作名称枚举。
    """

    SCOPE_LIST = "scope_list"
    SCOPE_DETAIL = "scope_detail"
    SCOPE_CREATE = "scope_create"
    SCOPE_UPDATE = "scope_update"
    SCOPE_DELETE = "scope_delete"
    ROLE_LIST = "role_list"
    ROLE_DETAIL = "role_detail"
    ROLE_CREATE = "role_create"
    ROLE_UPDATE = "role_update"
    ROLE_SCOPE_REPLACE = "role_scope_replace"
    ROLE_DELETE = "role_delete"
    USER_LIST = "user_list"
    USER_DETAIL = "user_detail"
    USER_CREATE = "user_create"
    USER_UPDATE = "user_update"
    USER_PASSWORD_RESET = "user_password_reset"
    USER_ROLE_REPLACE = "user_role_replace"
    USER_DELETE = "user_delete"
    USER_DISABLE = "user_disable"
    USER_ENABLE = "user_enable"


class AdminIdentityPayloadKind(StrEnum):
    """
    管理员身份载荷类型枚举。
    """

    SCOPE = ADMIN_SCOPE_PAYLOAD_KIND
    SCOPE_LIST = ADMIN_SCOPE_LIST_KIND
    SCOPE_CREATE = ADMIN_SCOPE_CREATE_KIND
    SCOPE_UPDATE = ADMIN_SCOPE_UPDATE_KIND
    SCOPE_DELETE_RESULT = ADMIN_SCOPE_DELETE_RESULT_KIND
    ROLE = ADMIN_ROLE_PAYLOAD_KIND
    ROLE_LIST = ADMIN_ROLE_LIST_KIND
    ROLE_CREATE = ADMIN_ROLE_CREATE_KIND
    ROLE_UPDATE = ADMIN_ROLE_UPDATE_KIND
    ROLE_SCOPE_REPLACE = ADMIN_ROLE_SCOPE_REPLACE_KIND
    ROLE_DELETE_RESULT = ADMIN_ROLE_DELETE_RESULT_KIND
    USER = ADMIN_USER_PAYLOAD_KIND
    USER_LIST = ADMIN_USER_LIST_KIND
    USER_CREATE = ADMIN_USER_CREATE_KIND
    USER_UPDATE = ADMIN_USER_UPDATE_KIND
    USER_PASSWORD_RESET = ADMIN_USER_PASSWORD_RESET_KIND
    USER_ROLE_REPLACE = ADMIN_USER_ROLE_REPLACE_KIND
    USER_DELETE_RESULT = ADMIN_USER_DELETE_RESULT_KIND
    USER_DISABLE = ADMIN_USER_DISABLE_KIND
    USER_ENABLE = ADMIN_USER_ENABLE_KIND
    USER_STATUS_RESULT = ADMIN_USER_STATUS_RESULT_KIND
    BUSINESS_ROLE = ADMIN_BUSINESS_ROLE_PAYLOAD_KIND
    BUSINESS_ROLE_LIST = ADMIN_BUSINESS_ROLE_LIST_KIND


ADMIN_IDENTITY_OPERATION_DETAIL_KINDS: dict[
    AdminIdentityOperationName,
    tuple[AdminIdentityPayloadKind, ...],
] = {
    AdminIdentityOperationName.SCOPE_LIST: (AdminIdentityPayloadKind.SCOPE_LIST,),
    AdminIdentityOperationName.SCOPE_DETAIL: (AdminIdentityPayloadKind.SCOPE,),
    AdminIdentityOperationName.SCOPE_CREATE: (
        AdminIdentityPayloadKind.SCOPE_CREATE,
        AdminIdentityPayloadKind.SCOPE,
    ),
    AdminIdentityOperationName.SCOPE_UPDATE: (
        AdminIdentityPayloadKind.SCOPE_UPDATE,
        AdminIdentityPayloadKind.SCOPE,
    ),
    AdminIdentityOperationName.SCOPE_DELETE: (AdminIdentityPayloadKind.SCOPE_DELETE_RESULT,),
    AdminIdentityOperationName.ROLE_LIST: (
        AdminIdentityPayloadKind.ROLE_LIST,
        AdminIdentityPayloadKind.BUSINESS_ROLE_LIST,
    ),
    AdminIdentityOperationName.ROLE_DETAIL: (AdminIdentityPayloadKind.ROLE,),
    AdminIdentityOperationName.ROLE_CREATE: (
        AdminIdentityPayloadKind.ROLE_CREATE,
        AdminIdentityPayloadKind.ROLE,
    ),
    AdminIdentityOperationName.ROLE_UPDATE: (
        AdminIdentityPayloadKind.ROLE_UPDATE,
        AdminIdentityPayloadKind.ROLE,
    ),
    AdminIdentityOperationName.ROLE_SCOPE_REPLACE: (
        AdminIdentityPayloadKind.ROLE_SCOPE_REPLACE,
        AdminIdentityPayloadKind.ROLE,
    ),
    AdminIdentityOperationName.ROLE_DELETE: (AdminIdentityPayloadKind.ROLE_DELETE_RESULT,),
    AdminIdentityOperationName.USER_LIST: (AdminIdentityPayloadKind.USER_LIST,),
    AdminIdentityOperationName.USER_DETAIL: (AdminIdentityPayloadKind.USER,),
    AdminIdentityOperationName.USER_CREATE: (
        AdminIdentityPayloadKind.USER_CREATE,
        AdminIdentityPayloadKind.USER,
    ),
    AdminIdentityOperationName.USER_UPDATE: (
        AdminIdentityPayloadKind.USER_UPDATE,
        AdminIdentityPayloadKind.USER,
    ),
    AdminIdentityOperationName.USER_PASSWORD_RESET: (
        AdminIdentityPayloadKind.USER_PASSWORD_RESET,
        AdminIdentityPayloadKind.USER,
    ),
    AdminIdentityOperationName.USER_ROLE_REPLACE: (
        AdminIdentityPayloadKind.USER_ROLE_REPLACE,
        AdminIdentityPayloadKind.USER,
    ),
    AdminIdentityOperationName.USER_DELETE: (
        AdminIdentityPayloadKind.USER_DELETE_RESULT,
        AdminIdentityPayloadKind.USER_STATUS_RESULT,
    ),
    AdminIdentityOperationName.USER_DISABLE: (
        AdminIdentityPayloadKind.USER_DISABLE,
        AdminIdentityPayloadKind.USER_STATUS_RESULT,
    ),
    AdminIdentityOperationName.USER_ENABLE: (
        AdminIdentityPayloadKind.USER_ENABLE,
        AdminIdentityPayloadKind.USER_STATUS_RESULT,
    ),
}

AdminIdentityDeleteResultKind: TypeAlias = Literal[
    "admin_scope_delete_result",
    "admin_role_delete_result",
    "admin_user_delete_result",
]


class AdminIdentityHeader(BaseModel):
    """
    管理员身份公共头。
    """

    model_config = ConfigDict(extra="forbid")

    kind: AdminIdentityPayloadKind
    schema_version: Literal["1.0"] = ADMIN_IDENTITY_SCHEMA_VERSION
    operation_name: AdminIdentityOperationName


class AdminIdentityDeleteResultPayload(BaseModel):
    """
    管理员身份删除结果载荷。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal[
        "admin_scope_delete_result",
        "admin_role_delete_result",
        "admin_user_delete_result",
    ]
    schema_version: Literal["1.0"] = ADMIN_IDENTITY_SCHEMA_VERSION
    target_id: str
    deleted: bool
    reason: str | None

    @classmethod
    def from_result(
        cls,
        *,
        kind: AdminIdentityDeleteResultKind,
        result: AdminIdentityDeleteResult,
    ) -> AdminIdentityDeleteResultPayload:
        """
        从删除结果构建载荷。
        """

        return cls(
            kind=kind,
            target_id=result.target_id,
            deleted=result.deleted,
            reason=result.reason,
        )
