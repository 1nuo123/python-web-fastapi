"""Codex 设备公钥仓储端口。"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from src.core.codex_contract.device_key_contract import CodexDeviceKeySnapshot


class CodexDeviceKeyRepositoryPort(Protocol):
    """设备公钥持久化的窄端口。"""

    def add(self, snapshot: CodexDeviceKeySnapshot) -> None: ...

    def save(self, snapshot: CodexDeviceKeySnapshot) -> None: ...

    def get_by_key_and_host(
        self,
        key_id: UUID,
        host_id: UUID,
    ) -> CodexDeviceKeySnapshot | None: ...

    def get_by_enrollment(self, enrollment_id: UUID) -> CodexDeviceKeySnapshot | None: ...

    def list_by_host_and_owner(
        self,
        host_id: UUID,
        owner_subject_id: str,
    ) -> list[CodexDeviceKeySnapshot]: ...

    def list_unconnected_created_before(
        self,
        *,
        created_before: datetime,
        limit: int,
    ) -> list[CodexDeviceKeySnapshot]: ...

    def revoke_all_by_host_and_owner(
        self,
        *,
        host_id: UUID,
        owner_subject_id: str,
        revoked_at: datetime,
    ) -> int: ...
