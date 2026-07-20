"""
管理员用户列表查询用例。
"""

from __future__ import annotations

from src.application.ports.admin_identity_port import (
    AdminIdentityPort,
    AdminUserListQuery,
    AdminUserPage,
)


class ListAdminUsersUsecase:
    """
    管理员用户列表查询用例。
    """

    def __init__(self, *, admin_identity_port: AdminIdentityPort) -> None:
        """
        初始化用例。
        """

        self._admin_identity_port = admin_identity_port

    def execute(self, query: AdminUserListQuery) -> AdminUserPage:
        """
        执行管理员用户列表查询。
        """

        return self._admin_identity_port.list_admin_users(query)
