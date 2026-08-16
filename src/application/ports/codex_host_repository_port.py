"""Codex 主机仓储应用端口。"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from src.core.codex_contract.host_contract import CodexHostObservation, CodexHostSnapshot


class CodexHostRepositoryPort(Protocol):
    """主机元数据仓储边界；所有查询必须显式携带所有者。"""

    def list_by_owner(self, owner_subject_id: str) -> list[CodexHostSnapshot]: ...

    def list_all(self) -> list[CodexHostSnapshot]: ...

    def count_active_by_owner(self, owner_subject_id: str) -> int: ...

    def get_by_id_and_owner(
        self,
        host_id: UUID,
        owner_subject_id: str,
    ) -> CodexHostSnapshot | None: ...

    def add(self, snapshot: CodexHostSnapshot) -> None: ...

    def save(self, snapshot: CodexHostSnapshot) -> None: ...

    def apply_observation(
        self,
        observation: CodexHostObservation,
    ) -> CodexHostSnapshot | None: ...

    def rename_if_version(
        self,
        *,
        host_id: UUID,
        owner_subject_id: str,
        expected_version: int,
        display_name: str,
        updated_at: datetime,
    ) -> CodexHostSnapshot | None: ...

    def revoke_if_version(
        self,
        *,
        host_id: UUID,
        owner_subject_id: str,
        expected_version: int,
        revoked_at: datetime,
    ) -> CodexHostSnapshot | None: ...
