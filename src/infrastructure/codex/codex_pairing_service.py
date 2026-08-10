"""Codex 主机配对码、Agent enroll 与凭据轮换服务。"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from src.application.ports.codex_control_port import CodexControlPort
from src.core.codex_contract.agent_device_auth_contract import (
    AgentDevicePrincipal,
    CodexAgentCredentialIssue,
)
from src.core.codex_contract.codex_runtime_contract import CodexRuntimeSettings
from src.core.codex_contract.host_contract import CodexHostSnapshot


@dataclass(frozen=True, slots=True)
class CodexPairingCodeIssue:
    """只在用户响应中返回的短期配对码。"""

    host_id: UUID
    pairing_code: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class _PairingRecord:
    host_id: UUID
    owner_subject_id: str
    expires_at: datetime


class CodexPairingService:
    """配对码只保存摘要，并确保每个摘要只能兑换一次。"""

    def __init__(self, *, control_port: CodexControlPort, settings: CodexRuntimeSettings) -> None:
        self._control_port = control_port
        self._settings = settings
        self._records: dict[str, _PairingRecord] = {}

    def issue(
        self,
        *,
        owner_subject_id: str,
        display_name: str,
        platform: str,
    ) -> CodexPairingCodeIssue:
        now = datetime.now(UTC)
        host_id = uuid4()
        expires_at = now + timedelta(seconds=self._settings.pairing_code_ttl_seconds)
        pairing_code = secrets.token_urlsafe(24)
        self._records[self._digest(pairing_code)] = _PairingRecord(
            host_id=host_id,
            owner_subject_id=owner_subject_id,
            expires_at=expires_at,
        )
        unit_of_work = self._control_port.create_unit_of_work()
        try:
            repository = self._control_port.create_codex_host_repository(unit_of_work.get_session())
            repository.add(
                CodexHostSnapshot(
                    host_id=host_id,
                    owner_subject_id=owner_subject_id,
                    display_name=display_name,
                    platform=platform,
                    status="enrolling",
                    created_at=now,
                    updated_at=now,
                    version=1,
                )
            )
            unit_of_work.commit()
        except BaseException:
            unit_of_work.rollback()
            self._records.pop(self._digest(pairing_code), None)
            raise
        finally:
            unit_of_work.dispose()
        return CodexPairingCodeIssue(host_id, pairing_code, expires_at)

    def enroll(
        self,
        *,
        pairing_code: str,
        host_id: UUID,
    ) -> tuple[UUID, str]:
        digest = self._digest(pairing_code)
        record = self._records.pop(digest, None)
        now = datetime.now(UTC)
        if record is None or record.host_id != host_id or record.expires_at <= now:
            raise ValueError("配对码无效、已使用或已过期。")
        token = secrets.token_urlsafe(48)
        credential_id = uuid4()
        unit_of_work = self._control_port.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            host_repository = self._control_port.create_codex_host_repository(session)
            host = host_repository.get_by_id_and_owner(host_id, record.owner_subject_id)
            if host is None:
                raise ValueError("配对主机不存在。")
            credential_repository = self._control_port.create_codex_agent_credential_repository(
                session
            )
            credential_repository.add(
                CodexAgentCredentialIssue(
                    credential_id=credential_id,
                    host_id=host_id,
                    token_digest=self._digest(token),
                    key_id=str(uuid4()),
                    status="active",
                    issued_at=now,
                )
            )
            host_repository.save(
                host.model_copy(
                    update={"status": "enrolling", "updated_at": now, "version": host.version + 1}
                )
            )
            unit_of_work.commit()
        except BaseException:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()
        return credential_id, token

    def rotate(self, principal: AgentDevicePrincipal) -> tuple[UUID, str]:
        now = datetime.now(UTC)
        token = secrets.token_urlsafe(48)
        credential_id = uuid4()
        unit_of_work = self._control_port.create_unit_of_work()
        try:
            repository = self._control_port.create_codex_agent_credential_repository(
                unit_of_work.get_session()
            )
            changed = repository.rotate(
                UUID(principal.credential_id),
                CodexAgentCredentialIssue(
                    credential_id=credential_id,
                    host_id=UUID(principal.host_id),
                    token_digest=self._digest(token),
                    key_id=str(uuid4()),
                    status="active",
                    issued_at=now,
                ),
                now,
            )
            if not changed:
                raise ValueError("Agent凭据不存在或已失效。")
            unit_of_work.commit()
        except BaseException:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()
        return credential_id, token

    def _digest(self, value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()
