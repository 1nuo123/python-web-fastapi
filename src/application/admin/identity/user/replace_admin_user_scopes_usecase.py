"""管理员用户直接 scope 替换用例。"""

from __future__ import annotations

from src.application.admin.identity.shared.admin_identity_command import (
    AdminUserScopeReplaceCommand,
)
from src.application.ports.admin_identity_port import (
    AdminIdentityPort,
    AdminUserSnapshot,
)


class ReplaceAdminUserScopesUsecase:
    """替换用户的直接授权 scope。"""

    def __init__(self, *, admin_identity_port: AdminIdentityPort) -> None:
        """初始化用例。"""

        self._admin_identity_port = admin_identity_port

    def execute(self, command: AdminUserScopeReplaceCommand) -> AdminUserSnapshot:
        """执行用户直接 scope 替换。"""

        return self._admin_identity_port.replace_admin_user_scopes(command)
