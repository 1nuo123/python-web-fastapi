"""Codex 审批仓储应用端口。"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from src.core.codex_contract.approval_contract import CodexApprovalAuditSnapshot


class CodexApprovalRepositoryPort(Protocol):
    """审批脱敏审计仓储边界。"""

    def list_by_owner(self, owner_subject_id: str) -> list[CodexApprovalAuditSnapshot]: ...

    def get_by_id_and_owner(
        self,
        approval_id: UUID,
        owner_subject_id: str,
    ) -> CodexApprovalAuditSnapshot | None: ...

    def add(self, snapshot: CodexApprovalAuditSnapshot) -> None: ...

    def save(self, snapshot: CodexApprovalAuditSnapshot) -> None: ...

    def claim_decision(
        self,
        *,
        approval_id: UUID,
        owner_subject_id: str,
        expected_version: int,
        decided_by: str,
        decision: str,
        decided_at: datetime,
    ) -> CodexApprovalAuditSnapshot | None: ...
