"""Codex 线程索引仓储应用端口。"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from src.core.codex_contract.thread_contract import (
    CodexActiveTurnUpdateMode,
    CodexConversationListQuery,
    CodexConversationPage,
    CodexThreadIndexSnapshot,
    CodexThreadRuntimeStateUpdate,
    CodexThreadStatus,
    CodexThreadTitleSource,
)
from src.core.codex_contract.turn_runtime_contract import CodexTurnRuntime


class CodexThreadRepositoryPort(Protocol):
    """不保存线程正文的索引仓储边界。"""

    def list_page_by_host_and_owner(
        self,
        host_id: UUID,
        owner_subject_id: str,
        query: CodexConversationListQuery,
    ) -> CodexConversationPage: ...

    def get_by_upstream_id_and_owner(
        self,
        host_id: UUID,
        upstream_thread_id: str,
        owner_subject_id: str,
    ) -> CodexThreadIndexSnapshot | None: ...

    def add(self, snapshot: CodexThreadIndexSnapshot) -> None: ...

    def save(self, snapshot: CodexThreadIndexSnapshot) -> None: ...

    def advance_activity(
        self,
        *,
        host_id: UUID,
        upstream_thread_id: str,
        owner_subject_id: str,
        occurred_at: datetime,
    ) -> CodexThreadIndexSnapshot | None: ...

    def promote_title(
        self,
        *,
        host_id: UUID,
        upstream_thread_id: str,
        owner_subject_id: str,
        display_name: str,
        source: CodexThreadTitleSource,
        updated_at: datetime,
    ) -> CodexThreadIndexSnapshot | None: ...

    def apply_runtime_state(
        self,
        *,
        host_id: UUID,
        upstream_thread_id: str,
        owner_subject_id: str,
        state_update: CodexThreadRuntimeStateUpdate,
    ) -> CodexThreadIndexSnapshot | None: ...

    def apply_turn_runtime(
        self,
        *,
        host_id: UUID,
        upstream_thread_id: str,
        owner_subject_id: str,
        runtime: CodexTurnRuntime,
        status: CodexThreadStatus,
        active_turn_mode: CodexActiveTurnUpdateMode,
        synchronized_at: datetime,
        expected_lease_generation: int | None,
    ) -> CodexThreadIndexSnapshot | None: ...

    def list_active_turn_runtimes(
        self,
        *,
        host_id: UUID,
        owner_subject_id: str,
    ) -> tuple[CodexThreadIndexSnapshot, ...]: ...

    def list_stalled_turn_runtime_candidates(
        self,
        *,
        activity_before: datetime,
        lease_expired_before: datetime,
    ) -> tuple[CodexThreadIndexSnapshot, ...]: ...
