"""Codex 设备签名挑战状态端口。"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from src.core.codex_contract.device_key_contract import DeviceChallengeStoreRecord


class CodexDeviceChallengeStorePort(Protocol):
    """挑战创建、读取和单次消费边界。"""

    async def create(self, record: DeviceChallengeStoreRecord) -> bool: ...

    async def read(self, challenge_id: UUID) -> DeviceChallengeStoreRecord | None: ...

    async def consume(
        self,
        *,
        challenge_id: UUID,
        expected_version: int,
    ) -> bool: ...
