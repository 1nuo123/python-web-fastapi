"""Codex 已认证设备注册意图分布式状态端口。"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from src.core.codex_contract.enrollment_intent_contract import (
    CodexEnrollmentIntentState,
    CodexEnrollmentIntentStoreRecord,
)


class CodexEnrollmentIntentStorePort(Protocol):
    """注册意图创建、读取和 CAS 的窄端口。"""

    async def create(self, record: CodexEnrollmentIntentStoreRecord) -> bool: ...

    async def read_by_id(self, intent_id: UUID) -> CodexEnrollmentIntentStoreRecord | None: ...

    async def read_by_token(
        self,
        intent_token: str,
    ) -> CodexEnrollmentIntentStoreRecord | None: ...

    async def transition(
        self,
        *,
        intent_id: UUID,
        expected_version: int,
        expected_state: CodexEnrollmentIntentState,
        next_record: CodexEnrollmentIntentStoreRecord,
    ) -> CodexEnrollmentIntentStoreRecord | None: ...
