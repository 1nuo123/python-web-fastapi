"""Codex 设备授权到通用原子状态的薄适配器。"""

from __future__ import annotations

import hmac
from datetime import timedelta
from uuid import UUID

from src.application.ports.codex_device_authorization_store_port import (
    CodexDeviceAuthorizationStorePort,
)
from src.core.codex_contract.device_authorization_contract import (
    DeviceAuthorizationState,
    DeviceAuthorizationStoreRecord,
)
from src.core.distributed_state_contract.atomic_state_contract import (
    AtomicStatePort,
    AtomicStateRecord,
)
from src.infrastructure.key_management.sensitive_digest_service import (
    SensitiveDigestService,
)

DEVICE_AUTHORIZATION_KEY_NAMESPACE = "codex:device_authorization"
USER_CODE_INDEX_NAMESPACE = "codex:device_authorization_user"


class CodexDeviceAuthorizationStore(CodexDeviceAuthorizationStorePort):
    """组合通用 CAS 与敏感摘要，不拥有 Redis client 或 Lua executor。"""

    def __init__(
        self,
        *,
        state: AtomicStatePort,
        digest_service: SensitiveDigestService,
        recovery_seconds: int = 86_400,
    ) -> None:
        self._state = state
        self._digest_service = digest_service
        self._recovery_seconds = recovery_seconds

    async def create(self, record: DeviceAuthorizationStoreRecord) -> bool:
        return await self._state.create_with_index(
            record=AtomicStateRecord(
                key=self._device_key(record.enrollment_id),
                value=record.model_dump_json(),
                version=record.version,
                expires_at=record.expires_at + timedelta(seconds=self._recovery_seconds),
            ),
            index_record=AtomicStateRecord(
                key=self._user_key_from_digest(record.user_code_digest),
                value=str(record.enrollment_id),
                version=1,
                expires_at=record.expires_at + timedelta(seconds=self._recovery_seconds),
            ),
        )

    async def read_by_device_code(
        self,
        *,
        enrollment_id: UUID,
        device_code: str,
    ) -> DeviceAuthorizationStoreRecord | None:
        record = await self._read(enrollment_id)
        if record is None:
            return None
        supplied_digest = self._digest_service.digest(device_code)
        if not hmac.compare_digest(record.device_code_digest, supplied_digest):
            return None
        return record

    async def read_by_user_code(
        self,
        user_code: str,
    ) -> DeviceAuthorizationStoreRecord | None:
        digest = self._digest_service.digest(user_code)
        index = await self._state.read(self._user_key_from_digest(digest))
        if index is None:
            return None
        try:
            enrollment_id = UUID(index.value)
        except ValueError:
            return None
        record = await self._read(enrollment_id)
        if record is None or not hmac.compare_digest(record.user_code_digest, digest):
            return None
        return record

    async def transition(
        self,
        *,
        enrollment_id: UUID,
        expected_version: int,
        expected_state: DeviceAuthorizationState,
        next_record: DeviceAuthorizationStoreRecord,
    ) -> DeviceAuthorizationStoreRecord | None:
        current = await self._read(enrollment_id)
        if (
            current is None
            or current.version != expected_version
            or current.state != expected_state
            or next_record.enrollment_id != enrollment_id
            or next_record.version != expected_version + 1
        ):
            return None
        changed = await self._state.compare_and_set(
            key=self._device_key(enrollment_id),
            expected_version=expected_version,
            next_value=next_record.model_dump_json(),
            expires_at=next_record.expires_at + timedelta(seconds=self._recovery_seconds),
        )
        return next_record if changed is not None else None

    async def _read(self, enrollment_id: UUID) -> DeviceAuthorizationStoreRecord | None:
        state = await self._state.read(self._device_key(enrollment_id))
        if state is None:
            return None
        return DeviceAuthorizationStoreRecord.model_validate_json(state.value)

    def _device_key(self, enrollment_id: UUID) -> str:
        return f"{DEVICE_AUTHORIZATION_KEY_NAMESPACE}:{enrollment_id}"

    def _user_key_from_digest(self, digest: str) -> str:
        return f"{USER_CODE_INDEX_NAMESPACE}:{digest}"
