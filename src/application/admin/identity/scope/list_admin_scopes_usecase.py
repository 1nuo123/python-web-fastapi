"""
管理员 scope 列表查询用例。
"""

from __future__ import annotations

from src.application.ports.admin_identity_port import (
    AdminIdentityPort,
    AdminScopeListQuery,
    AdminScopeSnapshot,
)


class ListAdminScopesUsecase:
    """
    管理员 scope 列表查询用例。
    """

    def __init__(self, *, admin_identity_port: AdminIdentityPort) -> None:
        """
        初始化用例。
        """

        self._admin_identity_port = admin_identity_port

    def execute(self, query: AdminScopeListQuery) -> list[AdminScopeSnapshot]:
        """
        执行管理员 scope 列表查询。
        """

        return self._admin_identity_port.list_admin_scopes(query)
