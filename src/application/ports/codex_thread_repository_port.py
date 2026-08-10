"""Codex 线程索引仓储应用端口。"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from src.core.codex_contract.thread_contract import CodexThreadIndexSnapshot


class CodexThreadRepositoryPort(Protocol):
    """不保存线程正文的索引仓储边界。"""

    def list_by_host_and_owner(
        self,
        host_id: UUID,
        owner_subject_id: str,
    ) -> list[CodexThreadIndexSnapshot]: ...

    def get_by_upstream_id_and_owner(
        self,
        host_id: UUID,
        upstream_thread_id: str,
        owner_subject_id: str,
    ) -> CodexThreadIndexSnapshot | None: ...

    def add(self, snapshot: CodexThreadIndexSnapshot) -> None: ...

    def save(self, snapshot: CodexThreadIndexSnapshot) -> None: ...
