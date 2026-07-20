"""
管理员角色删除用例。
"""

from __future__ import annotations

from src.application.admin.identity.shared.admin_identity_command import (
    AdminRoleDeleteCommand,
)
from src.application.ports.admin_identity_port import (
    AdminIdentityDeleteResult,
    AdminIdentityPort,
)


class DeleteAdminRoleUsecase:
    """
    管理员角色删除用例。
    """

    def __init__(self, *, admin_identity_port: AdminIdentityPort) -> None:
        """
        初始化用例。
        """

        self._admin_identity_port = admin_identity_port

    def execute(self, command: AdminRoleDeleteCommand) -> AdminIdentityDeleteResult:
        """
        执行管理员角色删除。
        """

        return self._admin_identity_port.delete_admin_role(command)
