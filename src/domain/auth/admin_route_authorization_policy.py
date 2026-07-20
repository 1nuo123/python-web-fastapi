"""
后台路由授权策略领域模块。

该模块位于领域层，供 API 适配器与基础设施仓储共同使用，避免低层模块
反向依赖 API 路由实现。
"""

from __future__ import annotations

from dataclasses import dataclass

from src.core.auth_contract.authorization_policy_contract import (
    RouteAuthorizationRequirement,
)
from src.domain.auth.auth_role_key import AuthRoleKey
from src.domain.auth.auth_scope_code import AuthScopeCode

ADMIN_TASK_QUERY_REQUIREMENT_NAME = "admin_task_query"
ADMIN_TASK_DISPATCH_REQUIREMENT_NAME = "admin_task_dispatch"
ADMIN_SETTINGS_RELOAD_REQUIREMENT_NAME = "admin_settings_reload"
ADMIN_LOG_QUERY_REQUIREMENT_NAME = "admin_log_query"
ADMIN_IDENTITY_READ_REQUIREMENT_NAME = "admin_identity_read"
ADMIN_IDENTITY_MANAGE_REQUIREMENT_NAME = "admin_identity_manage"
ADMIN_IDENTITY_USER_MANAGE_REQUIREMENT_NAME = "admin_identity_user_manage"
ADMIN_IDENTITY_ROLE_MANAGE_REQUIREMENT_NAME = "admin_identity_role_manage"
ADMIN_IDENTITY_SCOPE_MANAGE_REQUIREMENT_NAME = "admin_identity_scope_manage"
ADMIN_IDENTITY_PASSWORD_RESET_REQUIREMENT_NAME = "admin_identity_password_reset"
ADMIN_IDENTITY_GRANT_ADMIN_REQUIREMENT_NAME = "admin_identity_grant_admin"
ADMIN_AUDIT_READ_REQUIREMENT_NAME = "admin_audit_read"
SYSTEM_INFO_REQUIREMENT_NAME = "system_info_read"
SECURITY_PROTECTION_REQUIREMENT_NAME = "security_protection_admin"

ADMIN_REQUIRED_ROLES: list[str] = [AuthRoleKey.ADMIN.value]
ADMIN_AUTH_READ_REQUIRED_SCOPES: list[str] = [AuthScopeCode.AUTH_READ.value]
ADMIN_AUTH_MANAGE_REQUIRED_SCOPES: list[str] = [AuthScopeCode.AUTH_MANAGE.value]
ADMIN_AUTH_USER_MANAGE_REQUIRED_SCOPES: list[str] = [AuthScopeCode.AUTH_USER_MANAGE.value]
ADMIN_AUTH_ROLE_MANAGE_REQUIRED_SCOPES: list[str] = [AuthScopeCode.AUTH_ROLE_MANAGE.value]
ADMIN_AUTH_SCOPE_MANAGE_REQUIRED_SCOPES: list[str] = [AuthScopeCode.AUTH_SCOPE_MANAGE.value]
ADMIN_AUTH_PASSWORD_RESET_REQUIRED_SCOPES: list[str] = [AuthScopeCode.AUTH_PASSWORD_RESET.value]
ADMIN_AUTH_GRANT_ADMIN_REQUIRED_SCOPES: list[str] = [AuthScopeCode.AUTH_GRANT_ADMIN.value]
ADMIN_SYSTEM_READ_REQUIRED_SCOPES: list[str] = [AuthScopeCode.SYSTEM_READ.value]
ADMIN_TASK_DISPATCH_REQUIRED_SCOPES: list[str] = [AuthScopeCode.TASK_DISPATCH.value]
ADMIN_SECURITY_MANAGE_REQUIRED_SCOPES: list[str] = [AuthScopeCode.SECURITY_MANAGE.value]


@dataclass(frozen=True, slots=True)
class ProtectedAdminScopeRegistry:
    """
    受保护后台 scope 注册表。
    """

    scope_codes: frozenset[str]

    @classmethod
    def from_requirements(
        cls,
        requirements: tuple[RouteAuthorizationRequirement, ...],
    ) -> ProtectedAdminScopeRegistry:
        """
        从后台路由授权要求派生受保护 scope 集合。
        """

        return cls(
            scope_codes=frozenset(
                str(scope) for requirement in requirements for scope in requirement.required_scopes
            )
        )

    def contains(self, scope_code: str) -> bool:
        """
        判断 scope 是否属于后台受保护集合。
        """

        return scope_code in self.scope_codes


ADMIN_TASK_QUERY_AUTHORIZATION_REQUIREMENT = RouteAuthorizationRequirement(
    requirement_name=ADMIN_TASK_QUERY_REQUIREMENT_NAME,
    required_roles=ADMIN_REQUIRED_ROLES,
    required_scopes=ADMIN_SYSTEM_READ_REQUIRED_SCOPES,
)
ADMIN_TASK_DISPATCH_AUTHORIZATION_REQUIREMENT = RouteAuthorizationRequirement(
    requirement_name=ADMIN_TASK_DISPATCH_REQUIREMENT_NAME,
    required_roles=ADMIN_REQUIRED_ROLES,
    required_scopes=ADMIN_TASK_DISPATCH_REQUIRED_SCOPES,
)
ADMIN_SETTINGS_RELOAD_AUTHORIZATION_REQUIREMENT = RouteAuthorizationRequirement(
    requirement_name=ADMIN_SETTINGS_RELOAD_REQUIREMENT_NAME,
    required_roles=ADMIN_REQUIRED_ROLES,
    required_scopes=ADMIN_SYSTEM_READ_REQUIRED_SCOPES,
)
ADMIN_LOG_QUERY_AUTHORIZATION_REQUIREMENT = RouteAuthorizationRequirement(
    requirement_name=ADMIN_LOG_QUERY_REQUIREMENT_NAME,
    required_roles=ADMIN_REQUIRED_ROLES,
    required_scopes=ADMIN_SYSTEM_READ_REQUIRED_SCOPES,
)
ADMIN_IDENTITY_READ_AUTHORIZATION_REQUIREMENT = RouteAuthorizationRequirement(
    requirement_name=ADMIN_IDENTITY_READ_REQUIREMENT_NAME,
    required_roles=ADMIN_REQUIRED_ROLES,
    required_scopes=ADMIN_AUTH_READ_REQUIRED_SCOPES,
)
ADMIN_IDENTITY_MANAGE_AUTHORIZATION_REQUIREMENT = RouteAuthorizationRequirement(
    requirement_name=ADMIN_IDENTITY_MANAGE_REQUIREMENT_NAME,
    required_roles=ADMIN_REQUIRED_ROLES,
    required_scopes=ADMIN_AUTH_MANAGE_REQUIRED_SCOPES,
)
ADMIN_IDENTITY_USER_MANAGE_AUTHORIZATION_REQUIREMENT = RouteAuthorizationRequirement(
    requirement_name=ADMIN_IDENTITY_USER_MANAGE_REQUIREMENT_NAME,
    required_roles=ADMIN_REQUIRED_ROLES,
    required_scopes=ADMIN_AUTH_USER_MANAGE_REQUIRED_SCOPES,
)
ADMIN_IDENTITY_ROLE_MANAGE_AUTHORIZATION_REQUIREMENT = RouteAuthorizationRequirement(
    requirement_name=ADMIN_IDENTITY_ROLE_MANAGE_REQUIREMENT_NAME,
    required_roles=ADMIN_REQUIRED_ROLES,
    required_scopes=ADMIN_AUTH_ROLE_MANAGE_REQUIRED_SCOPES,
)
ADMIN_IDENTITY_SCOPE_MANAGE_AUTHORIZATION_REQUIREMENT = RouteAuthorizationRequirement(
    requirement_name=ADMIN_IDENTITY_SCOPE_MANAGE_REQUIREMENT_NAME,
    required_roles=ADMIN_REQUIRED_ROLES,
    required_scopes=ADMIN_AUTH_SCOPE_MANAGE_REQUIRED_SCOPES,
)
ADMIN_IDENTITY_PASSWORD_RESET_AUTHORIZATION_REQUIREMENT = RouteAuthorizationRequirement(
    requirement_name=ADMIN_IDENTITY_PASSWORD_RESET_REQUIREMENT_NAME,
    required_roles=ADMIN_REQUIRED_ROLES,
    required_scopes=ADMIN_AUTH_PASSWORD_RESET_REQUIRED_SCOPES,
)
ADMIN_IDENTITY_GRANT_ADMIN_AUTHORIZATION_REQUIREMENT = RouteAuthorizationRequirement(
    requirement_name=ADMIN_IDENTITY_GRANT_ADMIN_REQUIREMENT_NAME,
    required_roles=ADMIN_REQUIRED_ROLES,
    required_scopes=ADMIN_AUTH_GRANT_ADMIN_REQUIRED_SCOPES,
)
ADMIN_AUDIT_READ_AUTHORIZATION_REQUIREMENT = RouteAuthorizationRequirement(
    requirement_name=ADMIN_AUDIT_READ_REQUIREMENT_NAME,
    required_roles=ADMIN_REQUIRED_ROLES,
    required_scopes=ADMIN_AUTH_READ_REQUIRED_SCOPES,
)
SYSTEM_INFO_AUTHORIZATION_REQUIREMENT = RouteAuthorizationRequirement(
    requirement_name=SYSTEM_INFO_REQUIREMENT_NAME,
    required_roles=ADMIN_REQUIRED_ROLES,
    required_scopes=ADMIN_SYSTEM_READ_REQUIRED_SCOPES,
)
SECURITY_PROTECTION_AUTHORIZATION_REQUIREMENT = RouteAuthorizationRequirement(
    requirement_name=SECURITY_PROTECTION_REQUIREMENT_NAME,
    required_roles=ADMIN_REQUIRED_ROLES,
    required_scopes=ADMIN_SECURITY_MANAGE_REQUIRED_SCOPES,
)
BUSINESS_ADMIN_AUTHORIZATION_REQUIREMENTS: tuple[RouteAuthorizationRequirement, ...] = (
    ADMIN_IDENTITY_READ_AUTHORIZATION_REQUIREMENT,
    ADMIN_IDENTITY_MANAGE_AUTHORIZATION_REQUIREMENT,
    ADMIN_IDENTITY_USER_MANAGE_AUTHORIZATION_REQUIREMENT,
    ADMIN_IDENTITY_ROLE_MANAGE_AUTHORIZATION_REQUIREMENT,
    ADMIN_IDENTITY_SCOPE_MANAGE_AUTHORIZATION_REQUIREMENT,
    ADMIN_IDENTITY_PASSWORD_RESET_AUTHORIZATION_REQUIREMENT,
    ADMIN_IDENTITY_GRANT_ADMIN_AUTHORIZATION_REQUIREMENT,
    ADMIN_AUDIT_READ_AUTHORIZATION_REQUIREMENT,
)
OPS_ONLY_AUTHORIZATION_REQUIREMENTS: tuple[RouteAuthorizationRequirement, ...] = (
    ADMIN_TASK_QUERY_AUTHORIZATION_REQUIREMENT,
    ADMIN_TASK_DISPATCH_AUTHORIZATION_REQUIREMENT,
    ADMIN_SETTINGS_RELOAD_AUTHORIZATION_REQUIREMENT,
    ADMIN_LOG_QUERY_AUTHORIZATION_REQUIREMENT,
    SYSTEM_INFO_AUTHORIZATION_REQUIREMENT,
    SECURITY_PROTECTION_AUTHORIZATION_REQUIREMENT,
)
ADMIN_ROUTE_AUTHORIZATION_REQUIREMENTS: tuple[RouteAuthorizationRequirement, ...] = (
    *BUSINESS_ADMIN_AUTHORIZATION_REQUIREMENTS,
    *OPS_ONLY_AUTHORIZATION_REQUIREMENTS,
)
PROTECTED_ADMIN_SCOPE_REGISTRY = ProtectedAdminScopeRegistry.from_requirements(
    ADMIN_ROUTE_AUTHORIZATION_REQUIREMENTS
)
PROTECTED_ADMIN_SCOPE_CODES: frozenset[str] = PROTECTED_ADMIN_SCOPE_REGISTRY.scope_codes
