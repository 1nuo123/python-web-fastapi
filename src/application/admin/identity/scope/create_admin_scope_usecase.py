"""
管理员 scope 创建用例。
"""

from __future__ import annotations

from src.application.admin.identity.shared.admin_identity_command import (
    AdminScopeCreateCommand,
)
from src.application.ports.admin_identity_port import (
    AdminIdentityPort,
    AdminScopeSnapshot,
)


class CreateAdminScopeUsecase:
    """
    管理员 scope 创建用例。
    """

    def __init__(self, *, admin_identity_port: AdminIdentityPort) -> None:
        """
        初始化用例。
        """

        self._admin_identity_port = admin_identity_port

    def execute(self, command: AdminScopeCreateCommand) -> AdminScopeSnapshot:
        """
        执行管理员 scope 创建。
        """

        return self._admin_identity_port.create_admin_scope(command)
