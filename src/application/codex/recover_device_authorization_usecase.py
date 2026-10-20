"""凭持久批准证据与原设备签名恢复首次绑定，不依赖短期授权索引。"""

from __future__ import annotations

import asyncio
import base64
import secrets
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from uuid import uuid4

from src.application.ports.codex_control_port import CodexControlPort
from src.application.ports.codex_device_challenge_store_port import CodexDeviceChallengeStorePort
from src.application.ports.signature_verifier_port import SignatureVerifierPort
from src.core.codex_contract.device_authorization_contract import (
    DeviceAuthorizationRecoveryRequest,
    DeviceAuthorizationRecoveryResult,
)
from src.core.codex_contract.device_key_contract import (
    CodexDeviceKeySnapshot,
    DeviceChallengeCanonicalMessage,
    DeviceChallengeIssue,
    DeviceChallengeStoreRecord,
    DeviceKeyState,
)
from src.core.cryptography_contract.signature_contract import (
    SignatureAlgorithm,
    SignatureVerificationRequest,
)
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.domain.codex.codex_error_code import CodexErrorCode


class RecoverDeviceAuthorizationUsecase:
    """与原授权共享仓储和挑战；恢复与清理通过设备行锁串行。"""

    def __init__(
        self,
        *,
        control_port: CodexControlPort,
        store: CodexDeviceChallengeStorePort,
        verifier: SignatureVerifierPort,
        recovery_seconds: int,
        challenge_seconds: int,
    ) -> None:
        self._control_port = control_port
        self._store = store
        self._verifier = verifier
        self._recovery_seconds = recovery_seconds
        self._challenge_seconds = challenge_seconds

    async def execute(
        self, request: DeviceAuthorizationRecoveryRequest
    ) -> DeviceChallengeIssue | DeviceAuthorizationRecoveryResult:
        key = await asyncio.to_thread(self._read_identity, request, activate=False)
        audience = f"codex.enrollment.recover:{request.enrollment_id}"
        if request.proof is None:
            now = datetime.now(UTC)
            challenge = DeviceChallengeIssue(
                challenge_id=uuid4(),
                host_id=key.host_id,
                key_id=key.key_id,
                nonce=secrets.token_urlsafe(32),
                audience=audience,
                issued_at=now,
                expires_at=now + timedelta(seconds=self._challenge_seconds),
            )
            if not await self._store.create(
                DeviceChallengeStoreRecord(
                    challenge=challenge,
                    owner_subject_id=key.owner_subject_id,
                    version=1,
                )
            ):
                raise self._invalid()
            return challenge
        proof = request.proof
        record = await self._store.read(proof.challenge_id)
        if (
            record is None
            or record.challenge.expires_at <= datetime.now(UTC)
            or record.owner_subject_id != key.owner_subject_id
            or record.challenge.audience != audience
            or record.challenge.key_id != key.key_id
            or proof.key_id != key.key_id
            or record.challenge.host_id != key.host_id
            or proof.host_id != key.host_id
        ):
            raise self._invalid()
        challenge = record.challenge
        canonical = DeviceChallengeCanonicalMessage(**challenge.model_dump())
        try:
            signature = base64.b64decode(proof.signature_base64, validate=True)
        except ValueError as exc:
            raise self._invalid() from exc
        if not self._verifier.verify(
            SignatureVerificationRequest(
                algorithm=SignatureAlgorithm.ED25519,
                public_key=key.public_key,
                message=canonical.canonical_bytes(),
                signature=signature,
            )
        ):
            raise self._invalid()
        if not await self._store.consume(
            challenge_id=proof.challenge_id, expected_version=record.version
        ):
            raise self._invalid()
        key = await asyncio.to_thread(self._read_identity, request, activate=True)
        return DeviceAuthorizationRecoveryResult(
            enrollment_id=key.enrollment_id,
            key_id=key.key_id,
            host_id=key.host_id,
        )

    def _read_identity(
        self, request: DeviceAuthorizationRecoveryRequest, *, activate: bool
    ) -> CodexDeviceKeySnapshot:
        uow = self._control_port.create_unit_of_work()
        try:
            session = uow.get_session()
            repository = self._control_port.create_codex_device_key_repository(session)
            key = repository.get_by_enrollment(request.enrollment_id)
            audit = self._control_port.create_codex_device_authorization_audit_repository(
                session
            ).get_approval(request.enrollment_id)
            now = datetime.now(UTC)
            if (
                key is None
                or audit is None
                or key.key_id != request.key_id
                or key.state not in {DeviceKeyState.PENDING, DeviceKeyState.ACTIVE}
                or key.revoked_at is not None
                or audit.host_id != key.host_id
                or audit.owner_subject_id != key.owner_subject_id
                or audit.occurred_at + timedelta(seconds=self._recovery_seconds) <= now
            ):
                raise self._invalid()
            host = self._control_port.create_codex_host_repository(session).get_by_id_and_owner(
                key.host_id, key.owner_subject_id
            )
            if host is None or host.revoked_at is not None:
                raise self._invalid()
            # Key rotation retains its own finalization transaction and may not enter this path.
            if any(
                other.key_id != key.key_id
                for other in repository.list_by_host_and_owner(key.host_id, key.owner_subject_id)
            ):
                raise self._invalid()
            if activate and key.state == DeviceKeyState.PENDING:
                key = key.model_copy(
                    update={
                        "state": DeviceKeyState.ACTIVE,
                        "activated_at": now,
                        "updated_at": now,
                        "version": key.version + 1,
                    }
                )
                repository.save(key)
            uow.commit()
            return key
        except BaseException:
            uow.rollback()
            raise
        finally:
            uow.dispose()

    @staticmethod
    def _invalid() -> HttpFaultException:
        return HttpFaultException(
            status_code=HTTPStatus.CONFLICT,
            error_code=CodexErrorCode.STATE_CONFLICT,
            message="原设备批准结果不可恢复，请重新连接；已撤销的身份不会恢复。",
        )
