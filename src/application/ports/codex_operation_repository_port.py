"""Codex 控制操作仓储应用端口。"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from src.core.codex_contract.operation_contract import CodexControlOperationSnapshot


class CodexOperationRepositoryPort(Protocol):
    """控制操作幂等与恢复元数据仓储边界。"""

    def get_by_actor_and_idempotency_key(
        self,
        actor_subject_id: str,
        idempotency_key: str,
    ) -> CodexControlOperationSnapshot | None: ...

    def get_by_id_and_owner(
        self,
        operation_id: UUID,
        owner_subject_id: str,
    ) -> CodexControlOperationSnapshot | None: ...

    def get_by_host_and_command_id(
        self,
        host_id: UUID,
        command_id: UUID,
    ) -> CodexControlOperationSnapshot | None: ...

    def list_pending_by_host(
        self,
        host_id: UUID,
        statuses: list[str],
    ) -> list[CodexControlOperationSnapshot]: ...

    def add(self, snapshot: CodexControlOperationSnapshot) -> None: ...

    def save(self, snapshot: CodexControlOperationSnapshot) -> None: ...
