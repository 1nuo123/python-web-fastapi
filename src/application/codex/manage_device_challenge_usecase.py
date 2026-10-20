"""Codex 设备签名挑战与一次性连接票据用例。"""

from __future__ import annotations

import asyncio
import base64
import binascii
import secrets
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from uuid import UUID, uuid4

from src.application.ports.codex_control_port import CodexControlPort
from src.application.ports.codex_device_challenge_store_port import (
    CodexDeviceChallengeStorePort,
)
from src.application.ports.signature_verifier_port import SignatureVerifierPort
from src.application.streaming.stream_access_ticket_service import (
    StreamAccessTicketService,
)
from src.core.codex_contract.agent_connection_contract import AgentConnectionTicketExpired
from src.core.codex_contract.agent_device_auth_contract import AgentDevicePrincipal
from src.core.codex_contract.device_key_contract import (
    DEVICE_CHALLENGE_AUDIENCE,
    DEVICE_CONNECTION_OPERATION,
    AgentConnectionTicketResponse,
    AgentConnectionTicketSubject,
    CodexDeviceKeySnapshot,
    DeviceChallengeCanonicalMessage,
    DeviceChallengeIssue,
    DeviceChallengeProof,
    DeviceChallengeStoreRecord,
    DeviceKeyState,
)
from src.core.cryptography_contract.signature_contract import (
    SignatureAlgorithm,
    SignatureVerificationRequest,
)
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.stream_contract.stream_access_contract import (
    StreamAccessTicketIssuedDetail,
)
from src.domain.codex.codex_error_code import CodexErrorCode

DEVICE_CHALLENGE_NONCE_BYTES = 32
DEVICE_CHALLENGE_INITIAL_VERSION = 1
ED25519_SIGNATURE_LENGTH_BYTES = 64


class DeviceKeyAcceptancePolicy:
    """判断 active key 和仍在宽限期的 rotating key。"""

    def accepts(self, key: CodexDeviceKeySnapshot, *, current_time: datetime) -> bool:
        if key.state == DeviceKeyState.ACTIVE and key.revoked_at is None:
            return True
        return (
            key.state == DeviceKeyState.ROTATING
            and key.revoked_at is None
            and key.retire_after is not None
            and key.retire_after > current_time
        )


class IssueDeviceChallengeUsecase:
    """只为未撤销主机的 active key 签发短期挑战。"""

    def __init__(
        self,
        *,
        store: CodexDeviceChallengeStorePort,
        control_port: CodexControlPort,
        ttl_seconds: int,
    ) -> None:
        self._store = store
        self._control_port = control_port
        self._ttl_seconds = ttl_seconds
        self._key_policy = DeviceKeyAcceptancePolicy()

    async def execute(self, *, host_id: UUID, key_id: UUID) -> DeviceChallengeIssue:
        owner_subject_id = await asyncio.to_thread(
            self._verify_active_identity,
            host_id=host_id,
            key_id=key_id,
        )
        issued_at = datetime.now(UTC)
        challenge = DeviceChallengeIssue(
            challenge_id=uuid4(),
            host_id=host_id,
            key_id=key_id,
            nonce=secrets.token_urlsafe(DEVICE_CHALLENGE_NONCE_BYTES),
            audience=DEVICE_CHALLENGE_AUDIENCE,
            issued_at=issued_at,
            expires_at=issued_at + timedelta(seconds=self._ttl_seconds),
        )
        created = await self._store.create(
            DeviceChallengeStoreRecord(
                challenge=challenge,
                owner_subject_id=owner_subject_id,
                version=DEVICE_CHALLENGE_INITIAL_VERSION,
            )
        )
        if not created:
            raise RuntimeError("设备挑战唯一标识发生冲突。")
        return challenge

    def _verify_active_identity(self, *, host_id: UUID, key_id: UUID) -> str:
        unit_of_work = self._control_port.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            key = self._control_port.create_codex_device_key_repository(
                session
            ).get_by_key_and_host(key_id, host_id)
            if key is None or not self._key_policy.accepts(key, current_time=datetime.now(UTC)):
                raise self._invalid()
            host = self._control_port.create_codex_host_repository(session).get_by_id_and_owner(
                host_id, key.owner_subject_id
            )
            if host is None or host.revoked_at is not None:
                raise self._invalid()
            return key.owner_subject_id
        finally:
            unit_of_work.dispose()

    def _invalid(self) -> HttpFaultException:
        return HttpFaultException(
            status_code=HTTPStatus.NOT_FOUND,
            error_code=CodexErrorCode.DEVICE_CHALLENGE_INVALID,
            message="设备身份不可用于签发挑战。",
        )


class VerifyDeviceChallengeUsecase:
    """验证 Ed25519 proof 并签发一次性 Agent WSS ticket。"""

    def __init__(
        self,
        *,
        store: CodexDeviceChallengeStorePort,
        control_port: CodexControlPort,
        signature_verifier: SignatureVerifierPort,
        ticket_service: StreamAccessTicketService,
    ) -> None:
        self._store = store
        self._control_port = control_port
        self._signature_verifier = signature_verifier
        self._ticket_service = ticket_service
        self._key_policy = DeviceKeyAcceptancePolicy()

    async def execute(
        self,
        *,
        proof: DeviceChallengeProof,
        client_ip: str | None,
    ) -> AgentConnectionTicketResponse:
        subject = await self.verify_identity(proof=proof)
        ticket_envelope = await self._ticket_service.issue(
            subject_id=subject.encode(),
            operation_name=DEVICE_CONNECTION_OPERATION,
            client_ip=client_ip,
        )
        if not isinstance(ticket_envelope.detail, StreamAccessTicketIssuedDetail):
            raise RuntimeError("Agent连接票据签发未返回issued扩展。")
        return AgentConnectionTicketResponse(
            ticket=ticket_envelope.detail.ticket,
            expires_at=ticket_envelope.detail.expires_at,
        )

    async def verify_identity(
        self,
        *,
        proof: DeviceChallengeProof,
    ) -> AgentConnectionTicketSubject:
        """验证并消费挑战，返回固定主机、key 和所有者。"""

        record = await self._store.read(proof.challenge_id)
        if record is None or record.challenge.expires_at <= datetime.now(UTC):
            raise HttpFaultException(
                status_code=HTTPStatus.UNAUTHORIZED,
                error_code=CodexErrorCode.DEVICE_CHALLENGE_EXPIRED,
                message="设备挑战已过期或已消费，请开始新的连接尝试。",
            )
        challenge = record.challenge
        if (
            challenge.host_id != proof.host_id
            or challenge.key_id != proof.key_id
            or challenge.audience != DEVICE_CHALLENGE_AUDIENCE
        ):
            raise self._invalid()
        key = await asyncio.to_thread(
            self._read_active_key,
            host_id=proof.host_id,
            key_id=proof.key_id,
            owner_subject_id=record.owner_subject_id,
        )
        signature = self._decode_signature(proof.signature_base64)
        canonical = DeviceChallengeCanonicalMessage(
            challenge_id=challenge.challenge_id,
            host_id=challenge.host_id,
            key_id=challenge.key_id,
            nonce=challenge.nonce,
            audience=challenge.audience,
            issued_at=challenge.issued_at,
            expires_at=challenge.expires_at,
        )
        if not self._signature_verifier.verify(
            SignatureVerificationRequest(
                algorithm=SignatureAlgorithm.ED25519,
                public_key=key.public_key,
                message=canonical.canonical_bytes(),
                signature=signature,
            )
        ):
            raise self._invalid()
        if not await self._store.consume(
            challenge_id=proof.challenge_id,
            expected_version=record.version,
        ):
            raise self._invalid()
        return AgentConnectionTicketSubject(
            host_id=proof.host_id,
            key_id=proof.key_id,
            owner_subject_id=record.owner_subject_id,
        )

    def _read_active_key(
        self,
        *,
        host_id: UUID,
        key_id: UUID,
        owner_subject_id: str,
    ) -> CodexDeviceKeySnapshot:
        unit_of_work = self._control_port.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            key = self._control_port.create_codex_device_key_repository(
                session
            ).get_by_key_and_host(key_id, host_id)
            host = self._control_port.create_codex_host_repository(session).get_by_id_and_owner(
                host_id, owner_subject_id
            )
            if (
                key is None
                or key.owner_subject_id != owner_subject_id
                or not self._key_policy.accepts(key, current_time=datetime.now(UTC))
                or key.revoked_at is not None
                or host is None
                or host.revoked_at is not None
            ):
                raise self._invalid()
            return key
        finally:
            unit_of_work.dispose()

    def _decode_signature(self, value: str) -> bytes:
        try:
            signature = base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise self._invalid() from exc
        if len(signature) != ED25519_SIGNATURE_LENGTH_BYTES:
            raise self._invalid()
        return signature

    def _invalid(self) -> HttpFaultException:
        return HttpFaultException(
            status_code=HTTPStatus.UNAUTHORIZED,
            error_code=CodexErrorCode.DEVICE_CHALLENGE_INVALID,
            message="设备挑战签名无效或已消费。",
        )


class ConsumeAgentConnectionTicketUsecase:
    """原子消费 Agent ticket 并恢复固定设备主体。"""

    def __init__(
        self,
        *,
        ticket_service: StreamAccessTicketService,
        control_port: CodexControlPort,
    ) -> None:
        self._ticket_service = ticket_service
        self._control_port = control_port
        self._key_policy = DeviceKeyAcceptancePolicy()

    async def execute(
        self,
        *,
        ticket: str,
        client_ip: str | None,
    ) -> AgentDevicePrincipal:
        record = await self._ticket_service.consume_record(
            ticket=ticket,
            operation_name=DEVICE_CONNECTION_OPERATION,
            client_ip=client_ip,
        )
        if record is None:
            raise AgentConnectionTicketExpired("Agent连接票据无效或已消费。")
        try:
            subject = AgentConnectionTicketSubject.decode(record.subject_id)
        except ValueError as exc:
            raise PermissionError("Agent连接票据主体结构无效。") from exc
        await asyncio.to_thread(self._verify_current_identity, subject)
        return AgentDevicePrincipal(
            credential_id=str(subject.key_id),
            host_id=str(subject.host_id),
            owner_subject_id=subject.owner_subject_id,
        )

    def _verify_current_identity(self, subject: AgentConnectionTicketSubject) -> None:
        """票据消费后回查事实源，撤销或轮换过期时立即拒绝。"""

        unit_of_work = self._control_port.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            key = self._control_port.create_codex_device_key_repository(
                session
            ).get_by_key_and_host(subject.key_id, subject.host_id)
            host = self._control_port.create_codex_host_repository(session).get_by_id_and_owner(
                subject.host_id, subject.owner_subject_id
            )
            if (
                key is None
                or key.owner_subject_id != subject.owner_subject_id
                or not self._key_policy.accepts(key, current_time=datetime.now(UTC))
                or host is None
                or host.revoked_at is not None
            ):
                raise PermissionError("Agent连接票据绑定身份已经失效。")
        finally:
            unit_of_work.dispose()
