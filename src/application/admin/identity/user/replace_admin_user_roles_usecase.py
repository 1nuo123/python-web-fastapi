"""
管理员用户角色替换用例。
"""

from __future__ import annotations

from src.application.admin.identity.shared.admin_identity_command import (
    AdminUserRoleReplaceCommand,
)
from src.application.ports.admin_identity_port import (
    AdminIdentityPort,
    AdminUserSnapshot,
)


class ReplaceAdminUserRolesUsecase:
    """
    管理员用户角色替换用例。
    """

    def __init__(self, *, admin_identity_port: AdminIdentityPort) -> None:
        """
        初始化用例。
        """

        self._admin_identity_port = admin_identity_port

    def execute(self, command: AdminUserRoleReplaceCommand) -> AdminUserSnapshot:
        """
        执行管理员用户角色替换。
        """

        return self._admin_identity_port.replace_admin_user_roles(command)
