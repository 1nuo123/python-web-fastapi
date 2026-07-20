"""
管理员角色 scope 替换用例。
"""

from __future__ import annotations

from src.application.admin.identity.shared.admin_identity_command import (
    AdminRoleScopeReplaceCommand,
)
from src.application.ports.admin_identity_port import (
    AdminIdentityPort,
    AdminRoleSnapshot,
)


class ReplaceAdminRoleScopesUsecase:
    """
    管理员角色 scope 替换用例。
    """

    def __init__(self, *, admin_identity_port: AdminIdentityPort) -> None:
        """
        初始化用例。
        """

        self._admin_identity_port = admin_identity_port

    def execute(self, command: AdminRoleScopeReplaceCommand) -> AdminRoleSnapshot:
        """
        执行管理员角色 scope 替换。
        """

        return self._admin_identity_port.replace_admin_role_scopes(command)
