"""Codex 工作区仓储应用端口。"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from src.core.codex_contract.workspace_contract import CodexWorkspaceSnapshot


class CodexWorkspaceRepositoryPort(Protocol):
    """工作区索引仓储边界。"""

    def list_by_host_and_owner(
        self,
        host_id: UUID,
        owner_subject_id: str,
        *,
        include_disabled: bool = False,
    ) -> list[CodexWorkspaceSnapshot]: ...

    def count_enabled_by_host_and_owner(
        self,
        host_id: UUID,
        owner_subject_id: str,
    ) -> int: ...

    def get_by_id_and_owner(
        self,
        workspace_id: UUID,
        owner_subject_id: str,
        *,
        include_disabled: bool = False,
    ) -> CodexWorkspaceSnapshot | None: ...

    def get_by_agent_key_and_owner(
        self,
        host_id: UUID,
        agent_workspace_key: str,
        owner_subject_id: str,
    ) -> CodexWorkspaceSnapshot | None: ...

    def add(self, snapshot: CodexWorkspaceSnapshot) -> None: ...

    def save(self, snapshot: CodexWorkspaceSnapshot) -> None: ...
