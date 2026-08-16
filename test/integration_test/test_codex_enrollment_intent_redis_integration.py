"""Codex 注册意图真实 Redis 原子性集成测试。"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from src.core.codex_contract.enrollment_intent_contract import (
    CodexEnrollmentIntentState,
    CodexEnrollmentIntentStoreRecord,
)
from src.infrastructure.codex.codex_enrollment_intent_store import (
    CODEX_ENROLLMENT_INTENT_KEY_NAMESPACE,
    CODEX_ENROLLMENT_INTENT_TOKEN_NAMESPACE,
    CodexEnrollmentIntentStore,
)
from src.infrastructure.distributed_state.redis_atomic_state import RedisAtomicState
from src.infrastructure.key_management.sensitive_digest_service import SensitiveDigestService
from test.redis_integration_support import RedisIntegrationAvailability

REDIS_TEST_URL_ENVIRONMENT_VARIABLE = "REDIS_TEST_URL"
REDIS_CONNECT_TIMEOUT_SECONDS = 2
TEST_DIGEST_SALT = "codex-enrollment-intent-integration"
TEST_INTENT_TOKEN_PREFIX = "codex-enrollment-token-"
TEST_TTL_SECONDS = 60


class TestCodexEnrollmentIntentRedisIntegration:
    """验证主记录、token 索引和 CAS 竞争均由 Redis 原子完成。"""

    @pytest.mark.asyncio
    @pytest.mark.redis
    @pytest.mark.integration
    async def test_create_and_transition_should_be_atomic_and_single_consumer(self) -> None:
        redis_resource = RedisIntegrationAvailability.create_resource(
            redis_url=os.environ[REDIS_TEST_URL_ENVIRONMENT_VARIABLE],
            timeout_seconds=REDIS_CONNECT_TIMEOUT_SECONDS,
        )
        digest_service = SensitiveDigestService(salt=TEST_DIGEST_SALT)
        key_prefix = f"test:codex-enrollment:{uuid4()}"
        state = RedisAtomicState(client=redis_resource.async_client, key_prefix=key_prefix)
        store = CodexEnrollmentIntentStore(
            state=state,
            digest_service=digest_service,
        )
        intent_id = uuid4()
        intent_token = f"{TEST_INTENT_TOKEN_PREFIX}{uuid4()}"
        token_digest = digest_service.digest(intent_token)
        record = CodexEnrollmentIntentStoreRecord(
            intent_id=intent_id,
            token_digest=token_digest,
            subject_id="subject-1",
            token_session_id=uuid4(),
            verification_uri="https://example.com/codex/verify-device",
            state=CodexEnrollmentIntentState.ISSUED,
            version=1,
            expires_at=datetime.now(UTC) + timedelta(seconds=TEST_TTL_SECONDS),
        )
        consuming = record.model_copy(
            update={
                "state": CodexEnrollmentIntentState.CONSUMING,
                "version": 2,
            }
        )
        try:
            created = await store.create(record)
            duplicate = await store.create(record)
            by_token = await store.read_by_token(intent_token)
            transitions = await asyncio.gather(
                *(
                    store.transition(
                        intent_id=intent_id,
                        expected_version=1,
                        expected_state=CodexEnrollmentIntentState.ISSUED,
                        next_record=consuming,
                    )
                    for _attempt in range(2)
                )
            )

            assert created is True
            assert duplicate is False
            assert by_token == record
            assert sum(result is not None for result in transitions) == 1
            assert await store.read_by_id(intent_id) == consuming
        finally:
            current = await store.read_by_id(intent_id)
            if current is not None:
                await state.delete(
                    key=f"{CODEX_ENROLLMENT_INTENT_KEY_NAMESPACE}:{intent_id}",
                    expected_version=current.version,
                )
            await state.delete(
                key=f"{CODEX_ENROLLMENT_INTENT_TOKEN_NAMESPACE}:{token_digest}",
                expected_version=1,
            )
            await redis_resource.close()
