"""
管理员角色详情读取用例。
"""

from __future__ import annotations

from src.application.ports.admin_identity_port import (
    AdminIdentityPort,
    AdminRoleSnapshot,
)


class GetAdminRoleUsecase:
    """
    管理员角色详情读取用例。
    """

    def __init__(self, *, admin_identity_port: AdminIdentityPort) -> None:
        """
        初始化用例。
        """

        self._admin_identity_port = admin_identity_port

    def execute(self, role_key: str) -> AdminRoleSnapshot:
        """
        执行管理员角色详情读取。
        """

        return self._admin_identity_port.get_admin_role(role_key)
