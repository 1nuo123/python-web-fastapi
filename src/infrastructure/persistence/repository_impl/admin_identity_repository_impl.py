"""管理员身份仓储组合入口。"""

from __future__ import annotations

from src.infrastructure.persistence.repository_impl.admin_role_repository import AdminRoleRepository
from src.infrastructure.persistence.repository_impl.admin_scope_repository import (
    AdminScopeRepository,
)
from src.infrastructure.persistence.repository_impl.admin_user_repository import AdminUserRepository


class AdminIdentityRepositoryImpl(
    AdminScopeRepository,
    AdminRoleRepository,
    AdminUserRepository,
):
    """组合 scope、role 和 user 聚合的管理员身份仓储。"""
