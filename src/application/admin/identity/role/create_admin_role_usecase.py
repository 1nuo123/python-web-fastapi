"""
管理员角色创建用例。
"""

from __future__ import annotations

from src.application.admin.identity.shared.admin_identity_command import (
    AdminRoleCreateCommand,
)
from src.application.ports.admin_identity_port import (
    AdminIdentityPort,
    AdminRoleSnapshot,
)


class CreateAdminRoleUsecase:
    """
    管理员角色创建用例。
    """

    def __init__(self, *, admin_identity_port: AdminIdentityPort) -> None:
        """
        初始化用例。
        """

        self._admin_identity_port = admin_identity_port

    def execute(self, command: AdminRoleCreateCommand) -> AdminRoleSnapshot:
        """
        执行管理员角色创建。
        """

        return self._admin_identity_port.create_admin_role(command)
