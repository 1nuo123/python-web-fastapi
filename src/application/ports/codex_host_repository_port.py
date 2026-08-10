"""Codex 主机仓储应用端口。"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from src.core.codex_contract.host_contract import CodexHostSnapshot


class CodexHostRepositoryPort(Protocol):
    """主机元数据仓储边界；所有查询必须显式携带所有者。"""

    def list_by_owner(self, owner_subject_id: str) -> list[CodexHostSnapshot]: ...

    def get_by_id_and_owner(
        self,
        host_id: UUID,
        owner_subject_id: str,
    ) -> CodexHostSnapshot | None: ...

    def add(self, snapshot: CodexHostSnapshot) -> None: ...

    def save(self, snapshot: CodexHostSnapshot) -> None: ...
