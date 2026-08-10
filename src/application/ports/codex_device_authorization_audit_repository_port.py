"""Codex 设备授权审计仓储端口。"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from src.core.codex_contract.device_authorization_audit_contract import (
    DeviceAuthorizationAuditSnapshot,
)


class CodexDeviceAuthorizationAuditRepositoryPort(Protocol):
    """设备授权审计的追加与幂等读取边界。"""

    def add(self, snapshot: DeviceAuthorizationAuditSnapshot) -> None: ...

    def get_by_enrollment_and_idempotency_key(
        self,
        *,
        enrollment_id: UUID,
        idempotency_key: str,
    ) -> DeviceAuthorizationAuditSnapshot | None: ...
