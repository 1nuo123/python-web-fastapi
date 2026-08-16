"""Codex 注册意图到通用原子状态的薄适配器。"""

from __future__ import annotations

import hmac
from uuid import UUID

from src.application.ports.codex_enrollment_intent_store_port import (
    CodexEnrollmentIntentStorePort,
)
from src.core.codex_contract.enrollment_intent_contract import (
    CodexEnrollmentIntentState,
    CodexEnrollmentIntentStoreRecord,
)
from src.core.distributed_state_contract.atomic_state_contract import (
    AtomicStatePort,
    AtomicStateRecord,
)
from src.infrastructure.key_management.sensitive_digest_service import (
    SensitiveDigestService,
)

CODEX_ENROLLMENT_INTENT_KEY_NAMESPACE = "codex:enrollment_intent"
CODEX_ENROLLMENT_INTENT_TOKEN_NAMESPACE = "codex:enrollment_intent_token"


class CodexEnrollmentIntentStore(CodexEnrollmentIntentStorePort):
    """组合通用 CAS 与敏感摘要，不持有 Redis client。"""

    def __init__(
        self,
        *,
        state: AtomicStatePort,
        digest_service: SensitiveDigestService,
    ) -> None:
        self._state = state
        self._digest_service = digest_service

    async def create(self, record: CodexEnrollmentIntentStoreRecord) -> bool:
        return await self._state.create_with_index(
            record=AtomicStateRecord(
                key=self._intent_key(record.intent_id),
                value=record.model_dump_json(),
                version=record.version,
                expires_at=record.expires_at,
            ),
            index_record=AtomicStateRecord(
                key=self._token_key(record.token_digest),
                value=str(record.intent_id),
                version=1,
                expires_at=record.expires_at,
            ),
        )

    async def read_by_id(self, intent_id: UUID) -> CodexEnrollmentIntentStoreRecord | None:
        record = await self._state.read(self._intent_key(intent_id))
        if record is None:
            return None
        return CodexEnrollmentIntentStoreRecord.model_validate_json(record.value)

    async def read_by_token(
        self,
        intent_token: str,
    ) -> CodexEnrollmentIntentStoreRecord | None:
        token_digest = self._digest_service.digest(intent_token)
        index = await self._state.read(self._token_key(token_digest))
        if index is None:
            return None
        try:
            intent_id = UUID(index.value)
        except ValueError:
            return None
        record = await self.read_by_id(intent_id)
        if record is None or not hmac.compare_digest(record.token_digest, token_digest):
            return None
        return record

    async def transition(
        self,
        *,
        intent_id: UUID,
        expected_version: int,
        expected_state: CodexEnrollmentIntentState,
        next_record: CodexEnrollmentIntentStoreRecord,
    ) -> CodexEnrollmentIntentStoreRecord | None:
        current = await self.read_by_id(intent_id)
        if (
            current is None
            or current.version != expected_version
            or current.state != expected_state
            or next_record.intent_id != intent_id
            or next_record.version != expected_version + 1
        ):
            return None
        changed = await self._state.compare_and_set(
            key=self._intent_key(intent_id),
            expected_version=expected_version,
            next_value=next_record.model_dump_json(),
            expires_at=next_record.expires_at,
        )
        return next_record if changed is not None else None

    def _intent_key(self, intent_id: UUID) -> str:
        return f"{CODEX_ENROLLMENT_INTENT_KEY_NAMESPACE}:{intent_id}"

    def _token_key(self, token_digest: str) -> str:
        return f"{CODEX_ENROLLMENT_INTENT_TOKEN_NAMESPACE}:{token_digest}"
