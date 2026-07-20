"""
管理员角色更新用例。
"""

from __future__ import annotations

from src.application.admin.identity.shared.admin_identity_command import (
    AdminRoleUpdateCommand,
)
from src.application.ports.admin_identity_port import (
    AdminIdentityPort,
    AdminRoleSnapshot,
)


class UpdateAdminRoleUsecase:
    """
    管理员角色更新用例。
    """

    def __init__(self, *, admin_identity_port: AdminIdentityPort) -> None:
        """
        初始化用例。
        """

        self._admin_identity_port = admin_identity_port

    def execute(self, command: AdminRoleUpdateCommand) -> AdminRoleSnapshot:
        """
        执行管理员角色更新。
        """

        return self._admin_identity_port.update_admin_role(command)
