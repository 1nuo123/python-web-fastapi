"""
管理员用户密码重置用例。
"""

from __future__ import annotations

from src.application.admin.identity.shared.admin_identity_command import (
    AdminUserPasswordResetCommand,
)
from src.application.ports.admin_identity_port import (
    AdminIdentityPort,
    AdminUserSnapshot,
)


class ResetAdminUserPasswordUsecase:
    """
    管理员用户密码重置用例。
    """

    def __init__(self, *, admin_identity_port: AdminIdentityPort) -> None:
        """
        初始化用例。
        """

        self._admin_identity_port = admin_identity_port

    def execute(self, command: AdminUserPasswordResetCommand) -> AdminUserSnapshot:
        """
        执行管理员用户密码重置。
        """

        return self._admin_identity_port.reset_admin_user_password(command)
