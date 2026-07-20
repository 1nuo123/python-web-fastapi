"""
管理员用户更新用例。
"""

from __future__ import annotations

from src.application.admin.identity.shared.admin_identity_command import (
    AdminUserUpdateCommand,
)
from src.application.ports.admin_identity_port import (
    AdminIdentityPort,
    AdminUserSnapshot,
)


class UpdateAdminUserUsecase:
    """
    管理员用户更新用例。
    """

    def __init__(self, *, admin_identity_port: AdminIdentityPort) -> None:
        """
        初始化用例。
        """

        self._admin_identity_port = admin_identity_port

    def execute(self, command: AdminUserUpdateCommand) -> AdminUserSnapshot:
        """
        执行管理员用户更新。
        """

        return self._admin_identity_port.update_admin_user(command)
