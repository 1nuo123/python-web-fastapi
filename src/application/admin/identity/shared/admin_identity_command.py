"""
管理员身份命令对象模块。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class InitialAdminCreateReason(StrEnum):
    """
    初始管理员创建结果原因枚举。
    """

    CREATED = "created"
    ALREADY_EXISTS = "already_exists"
    ADMIN_EXISTS = "admin_exists"
    CONFIRMATION_INVALID = "confirmation_invalid"
    RUNTIME_ERROR = "runtime_error"


@dataclass(slots=True)
class AdminScopeCreateCommand:
    """
    管理员 scope 创建命令。

    :ivar scope_code: 作用域编码。
    :vartype scope_code: str
    :ivar scope_name: 作用域展示名称。
    :vartype scope_name: str
    :ivar description: 作用域说明。
    :vartype description: str | None
    :ivar enabled: 是否启用。
    :vartype enabled: bool
    """

    scope_code: str
    scope_name: str
    description: str | None
    enabled: bool


@dataclass(slots=True)
class AdminScopeUpdateCommand:
    """
    管理员 scope 更新命令。
    """

    actor_subject_id: str
    scope_code: str
    scope_name: str | None
    description: str | None
    enabled: bool | None


@dataclass(slots=True)
class AdminScopeDeleteCommand:
    """
    管理员 scope 删除命令。
    """

    scope_code: str


@dataclass(slots=True)
class AdminRoleCreateCommand:
    """
    管理员角色创建命令。
    """

    role_key: str
    role_name: str
    scope_codes: list[str]
    grant_confirmed: bool = False


@dataclass(slots=True)
class AdminRoleUpdateCommand:
    """
    管理员角色更新命令。
    """

    role_key: str
    role_name: str


@dataclass(slots=True)
class AdminRoleScopeReplaceCommand:
    """
    管理员角色 scope 替换命令。
    """

    actor_subject_id: str
    role_key: str
    scope_codes: list[str]


@dataclass(slots=True)
class AdminRoleDeleteCommand:
    """
    管理员角色删除命令。
    """

    actor_subject_id: str
    role_key: str


@dataclass(slots=True)
class AdminUserCreateCommand:
    """
    管理员用户创建命令。
    """

    username: str
    password_plain: str
    role_keys: list[str]
    subject_id: str | None = None


@dataclass(slots=True)
class AdminUserUpdateCommand:
    """
    管理员用户更新命令。
    """

    actor_subject_id: str
    subject_id: str
    username: str | None
    is_active: bool | None


@dataclass(slots=True)
class AdminUserPasswordResetCommand:
    """
    管理员用户密码重置命令。
    """

    actor_subject_id: str
    subject_id: str
    password_plain: str


@dataclass(slots=True)
class AdminUserRoleReplaceCommand:
    """
    管理员用户角色替换命令。
    """

    actor_subject_id: str
    subject_id: str
    role_keys: list[str]


@dataclass(slots=True)
class AdminUserDeleteCommand:
    """
    管理员用户停用命令。
    """

    actor_subject_id: str
    subject_id: str
    reason: str | None = None


@dataclass(slots=True)
class InitialAdminCreateCommand:
    """
    初始管理员创建命令。
    """

    username: str
    password_plain: str
    subject_id: str | None
    confirmation: str


@dataclass(slots=True)
class InitialAdminCreateResult:
    """
    初始管理员创建结果。
    """

    created: bool
    subject_id: str | None
    reason: InitialAdminCreateReason
