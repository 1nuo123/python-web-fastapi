"""
管理员身份应用端口。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from src.application.admin.identity.shared.admin_identity_command import (
    AdminRoleCreateCommand,
    AdminRoleDeleteCommand,
    AdminRoleScopeReplaceCommand,
    AdminRoleUpdateCommand,
    AdminScopeCreateCommand,
    AdminScopeDeleteCommand,
    AdminScopeUpdateCommand,
    AdminUserCreateCommand,
    AdminUserDeleteCommand,
    AdminUserPasswordResetCommand,
    AdminUserRoleReplaceCommand,
    AdminUserUpdateCommand,
    InitialAdminCreateResult,
)

ADMIN_IDENTITY_QUERY_LIMIT_DEFAULT = 50
ADMIN_IDENTITY_QUERY_LIMIT_MINIMUM = 1
ADMIN_IDENTITY_QUERY_LIMIT_MAXIMUM = 200
ADMIN_IDENTITY_QUERY_OFFSET_MINIMUM = 0


class AdminScopeKind(StrEnum):
    """
    管理员 scope 类型枚举。
    """

    BUILTIN = "builtin"
    CUSTOM = "custom"


class BusinessAdminRoleKey(StrEnum):
    """
    预定义业务角色键枚举。
    """

    CUSTOMER_SERVICE = "customer_service"
    BUSINESS_OPERATOR = "business_operator"


@dataclass(slots=True)
class AdminScopeListQuery:
    """
    管理员 scope 列表查询。
    """

    keyword: str | None
    enabled: bool | None
    limit: int


@dataclass(slots=True)
class AdminRoleListQuery:
    """
    管理员角色列表查询。
    """

    keyword: str | None
    page_size: int
    offset: int
    business_only: bool = False


@dataclass(slots=True)
class AdminUserListQuery:
    """
    管理员用户列表查询。
    """

    keyword: str | None
    role_key: str | None
    is_active: bool | None
    page_size: int
    offset: int


@dataclass(slots=True)
class AdminScopeSnapshot:
    """
    管理员 scope 快照。
    """

    scope_code: str
    scope_name: str
    description: str | None
    scope_kind: AdminScopeKind
    enabled: bool


@dataclass(slots=True)
class AdminRoleSnapshot:
    """
    管理员角色快照。
    """

    role_key: str
    role_name: str
    scope_codes: list[str]
    user_count: int


@dataclass(slots=True)
class AdminUserSnapshot:
    """
    管理员用户快照。
    """

    subject_id: str
    username: str
    is_active: bool
    role_keys: list[str]
    scope_codes: list[str]


@dataclass(slots=True)
class AdminRolePage:
    """
    管理员业务角色分页结果。
    """

    roles: list[AdminRoleSnapshot]
    page_size: int
    offset: int
    total: int


@dataclass(slots=True)
class AdminUserPage:
    """
    管理员用户分页结果。
    """

    users: list[AdminUserSnapshot]
    page_size: int
    offset: int
    total: int


@dataclass(slots=True)
class AdminIdentityDeleteResult:
    """
    管理员身份删除结果。
    """

    target_id: str
    deleted: bool
    reason: str | None


class AdminIdentityPort(Protocol):
    """
    管理员身份端口。
    """

    def list_admin_scopes(
        self,
        query: AdminScopeListQuery,
    ) -> list[AdminScopeSnapshot]:
        """
        查询管理员 scope 列表。
        """

    def get_admin_scope(self, scope_code: str) -> AdminScopeSnapshot:
        """
        读取管理员 scope 详情。
        """

    def create_admin_scope(
        self,
        command: AdminScopeCreateCommand,
    ) -> AdminScopeSnapshot:
        """
        创建管理员 scope。
        """

    def update_admin_scope(
        self,
        command: AdminScopeUpdateCommand,
    ) -> AdminScopeSnapshot:
        """
        更新管理员 scope。
        """

    def delete_admin_scope(
        self,
        command: AdminScopeDeleteCommand,
    ) -> AdminIdentityDeleteResult:
        """
        删除管理员 scope。
        """

    def list_admin_roles(self, query: AdminRoleListQuery) -> AdminRolePage:
        """
        查询管理员角色列表。
        """

    def get_admin_role(self, role_key: str) -> AdminRoleSnapshot:
        """
        读取管理员角色详情。
        """

    def create_admin_role(
        self,
        command: AdminRoleCreateCommand,
    ) -> AdminRoleSnapshot:
        """
        创建管理员角色。
        """

    def update_admin_role(
        self,
        command: AdminRoleUpdateCommand,
    ) -> AdminRoleSnapshot:
        """
        更新管理员角色。
        """

    def replace_admin_role_scopes(
        self,
        command: AdminRoleScopeReplaceCommand,
    ) -> AdminRoleSnapshot:
        """
        替换管理员角色 scope。
        """

    def delete_admin_role(
        self,
        command: AdminRoleDeleteCommand,
    ) -> AdminIdentityDeleteResult:
        """
        删除管理员角色。
        """

    def list_admin_users(self, query: AdminUserListQuery) -> AdminUserPage:
        """
        查询管理员用户列表。
        """

    def get_admin_user(self, subject_id: str) -> AdminUserSnapshot:
        """
        读取管理员用户详情。
        """

    def create_admin_user(
        self,
        command: AdminUserCreateCommand,
    ) -> AdminUserSnapshot:
        """
        创建管理员用户。
        """

    def update_admin_user(
        self,
        command: AdminUserUpdateCommand,
    ) -> AdminUserSnapshot:
        """
        更新管理员用户。
        """

    def reset_admin_user_password(
        self,
        command: AdminUserPasswordResetCommand,
    ) -> AdminUserSnapshot:
        """
        重置管理员用户密码。
        """

    def replace_admin_user_roles(
        self,
        command: AdminUserRoleReplaceCommand,
    ) -> AdminUserSnapshot:
        """
        替换管理员用户角色。
        """

    def delete_admin_user(
        self,
        command: AdminUserDeleteCommand,
    ) -> AdminIdentityDeleteResult:
        """
        停用管理员用户。
        """

    def create_initial_admin_user(
        self,
        *,
        username: str,
        password_hash: str,
        subject_id: str | None,
    ) -> InitialAdminCreateResult:
        """
        创建首个管理员用户。
        """
