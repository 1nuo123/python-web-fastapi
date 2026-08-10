"""Codex 设备挑战到通用原子状态的薄适配器。"""

from __future__ import annotations

from uuid import UUID

from src.application.ports.codex_device_challenge_store_port import (
    CodexDeviceChallengeStorePort,
)
from src.core.codex_contract.device_key_contract import DeviceChallengeStoreRecord
from src.core.distributed_state_contract.atomic_state_contract import (
    AtomicStatePort,
    AtomicStateRecord,
)

DEVICE_CHALLENGE_KEY_NAMESPACE = "codex:device_challenge"


class CodexDeviceChallengeStore(CodexDeviceChallengeStorePort):
    """只表达挑战业务语义，不拥有 Redis client。"""

    def __init__(self, *, state: AtomicStatePort) -> None:
        self._state = state

    async def create(self, record: DeviceChallengeStoreRecord) -> bool:
        return await self._state.create(
            AtomicStateRecord(
                key=self._key(record.challenge.challenge_id),
                value=record.model_dump_json(),
                version=record.version,
                expires_at=record.challenge.expires_at,
            )
        )

    async def read(self, challenge_id: UUID) -> DeviceChallengeStoreRecord | None:
        record = await self._state.read(self._key(challenge_id))
        if record is None:
            return None
        return DeviceChallengeStoreRecord.model_validate_json(record.value)

    async def consume(
        self,
        *,
        challenge_id: UUID,
        expected_version: int,
    ) -> bool:
        return await self._state.delete(
            key=self._key(challenge_id),
            expected_version=expected_version,
        )

    def _key(self, challenge_id: UUID) -> str:
        return f"{DEVICE_CHALLENGE_KEY_NAMESPACE}:{challenge_id}"
