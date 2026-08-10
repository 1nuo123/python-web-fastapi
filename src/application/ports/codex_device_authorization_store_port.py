"""Codex 设备授权分布式状态端口。"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from src.core.codex_contract.device_authorization_contract import (
    DeviceAuthorizationState,
    DeviceAuthorizationStoreRecord,
)


class CodexDeviceAuthorizationStorePort(Protocol):
    """设备授权创建、查找和 CAS 的窄端口。"""

    async def create(self, record: DeviceAuthorizationStoreRecord) -> bool: ...

    async def read_by_device_code(
        self,
        *,
        enrollment_id: UUID,
        device_code: str,
    ) -> DeviceAuthorizationStoreRecord | None: ...

    async def read_by_user_code(
        self,
        user_code: str,
    ) -> DeviceAuthorizationStoreRecord | None: ...

    async def transition(
        self,
        *,
        enrollment_id: UUID,
        expected_version: int,
        expected_state: DeviceAuthorizationState,
        next_record: DeviceAuthorizationStoreRecord,
    ) -> DeviceAuthorizationStoreRecord | None: ...
