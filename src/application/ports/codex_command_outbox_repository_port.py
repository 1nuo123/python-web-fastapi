"""Codex command outbox 仓储端口。"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from src.core.codex_contract.command_outbox_contract import CodexCommandOutboxSnapshot


class CodexCommandOutboxRepositoryPort(Protocol):
    """同 operation UoW 写入并支持 SKIP LOCKED claim。"""

    def add(self, snapshot: CodexCommandOutboxSnapshot) -> None: ...

    def save(self, snapshot: CodexCommandOutboxSnapshot) -> None: ...

    def get_by_command_id(self, command_id: UUID) -> CodexCommandOutboxSnapshot | None: ...

    def claim_ready(
        self,
        *,
        claimed_by: str,
        current_time: datetime,
        stale_before: datetime,
        limit: int,
    ) -> list[CodexCommandOutboxSnapshot]: ...

    def claim_by_command_id(
        self,
        *,
        command_id: UUID,
        claimed_by: str,
        current_time: datetime,
    ) -> CodexCommandOutboxSnapshot | None: ...

    def delete_completed_before(self, completed_before: datetime) -> int: ...
