"""Codex enrollment intent 创建、索引读取与 CAS 路径测试。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from src.core.codex_contract.enrollment_intent_contract import (
    CodexEnrollmentIntentState,
    CodexEnrollmentIntentStoreRecord,
)
from src.infrastructure.codex.codex_enrollment_intent_store import CodexEnrollmentIntentStore
from src.infrastructure.distributed_state.memory_atomic_state import MemoryAtomicState
from src.infrastructure.key_management.sensitive_digest_service import SensitiveDigestService

TEST_INTENT_TOKEN = "intent-token-with-more-than-thirty-two-characters"
TEST_DIGEST_SALT = "codex-enrollment-intent-test-salt"


class TestCodexEnrollmentIntentPath:
    """验证一次性 token 索引、状态迁移和错误版本竞争。"""

    @pytest.mark.asyncio
    async def test_store_should_create_read_and_transition_once(self) -> None:
        digest_service = SensitiveDigestService(salt=TEST_DIGEST_SALT)
        store = CodexEnrollmentIntentStore(
            state=MemoryAtomicState(),
            digest_service=digest_service,
        )
        current = self._record(digest_service)

        assert await store.create(current) is True
        assert await store.create(current) is False
        assert await store.read_by_token(TEST_INTENT_TOKEN) == current

        consuming = current.model_copy(
            update={
                "state": CodexEnrollmentIntentState.CONSUMING,
                "version": current.version + 1,
            }
        )
        changed = await store.transition(
            intent_id=current.intent_id,
            expected_version=current.version,
            expected_state=CodexEnrollmentIntentState.ISSUED,
            next_record=consuming,
        )
        stale = await store.transition(
            intent_id=current.intent_id,
            expected_version=current.version,
            expected_state=CodexEnrollmentIntentState.ISSUED,
            next_record=consuming,
        )

        assert changed == consuming
        assert stale is None

    @pytest.mark.asyncio
    async def test_expired_record_should_be_removed_by_state_store(self) -> None:
        digest_service = SensitiveDigestService(salt=TEST_DIGEST_SALT)
        store = CodexEnrollmentIntentStore(
            state=MemoryAtomicState(),
            digest_service=digest_service,
        )
        expired = self._record(
            digest_service,
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )

        assert await store.create(expired) is True
        assert await store.read_by_id(expired.intent_id) is None
        assert await store.read_by_token(TEST_INTENT_TOKEN) is None

    def _record(
        self,
        digest_service: SensitiveDigestService,
        *,
        expires_at: datetime | None = None,
    ) -> CodexEnrollmentIntentStoreRecord:
        return CodexEnrollmentIntentStoreRecord(
            intent_id=uuid4(),
            token_digest=digest_service.digest(TEST_INTENT_TOKEN),
            subject_id="subject-1",
            token_session_id=uuid4(),
            verification_uri="https://app.example.com/codex/verify-device",
            state=CodexEnrollmentIntentState.ISSUED,
            version=1,
            expires_at=expires_at or datetime.now(UTC) + timedelta(minutes=5),
        )
