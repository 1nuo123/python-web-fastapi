"""Codex 资源所有权纯策略。"""


class CodexWorkspaceAccessPolicy:
    """统一比较认证主体与资源所有者。"""

    def can_access(self, *, subject_id: str, owner_subject_id: str) -> bool:
        """返回主体是否拥有资源，不区分不存在与越权。"""

        return subject_id == owner_subject_id
