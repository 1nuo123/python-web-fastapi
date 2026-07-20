"""
管理员用户停用用例。
"""

from __future__ import annotations

from src.application.admin.identity.shared.admin_identity_command import (
    AdminUserDeleteCommand,
)
from src.application.ports.admin_identity_port import (
    AdminIdentityDeleteResult,
    AdminIdentityPort,
)


class DeleteAdminUserUsecase:
    """
    管理员用户停用用例。
    """

    def __init__(self, *, admin_identity_port: AdminIdentityPort) -> None:
        """
        初始化用例。
        """

        self._admin_identity_port = admin_identity_port

    def execute(self, command: AdminUserDeleteCommand) -> AdminIdentityDeleteResult:
        """
        执行管理员用户停用。
        """

        return self._admin_identity_port.delete_admin_user(command)
