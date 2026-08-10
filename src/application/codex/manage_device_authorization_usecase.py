"""Codex 自助设备授权用例。"""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from uuid import UUID, uuid4

from src.application.ports.codex_control_port import CodexControlPort
from src.application.ports.codex_device_authorization_store_port import (
    CodexDeviceAuthorizationStorePort,
)
from src.application.ports.sensitive_digest_port import SensitiveDigestPort
from src.application.ports.signature_verifier_port import SignatureVerifierPort
from src.core.codex_contract.device_authorization_audit_contract import (
    DeviceAuthorizationAuditSnapshot,
)
from src.core.codex_contract.device_authorization_contract import (
    DeviceAuthorizationCreateDetail,
    DeviceAuthorizationDecideRequest,
    DeviceAuthorizationDecision,
    DeviceAuthorizationEnvelope,
    DeviceAuthorizationHeader,
    DeviceAuthorizationIssuedDetail,
    DeviceAuthorizationState,
    DeviceAuthorizationStatusDetail,
    DeviceAuthorizationStoreRecord,
    DeviceEnrollmentCanonicalMessage,
)
from src.core.codex_contract.device_key_contract import (
    CodexDeviceKeySnapshot,
    DeviceKeyState,
)
from src.core.codex_contract.host_contract import CodexHostSnapshot
from src.core.cryptography_contract.signature_contract import (
    SignatureAlgorithm,
    SignatureVerificationRequest,
)
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.domain.codex.codex_error_code import CodexErrorCode
from src.domain.codex.host_status import CodexHostStatus

USER_CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
USER_CODE_RANDOM_LENGTH = 8
USER_CODE_GROUP_LENGTH = 4
DEVICE_CODE_RANDOM_BYTES = 32
DEVICE_PUBLIC_KEY_LENGTH_BYTES = 32
ED25519_SIGNATURE_LENGTH_BYTES = 64
DEVICE_AUTHORIZATION_INITIAL_VERSION = 1
DEVICE_AUTHORIZATION_VERIFICATION_PATH = "/codex/verify-device"
DEVICE_AUTHORIZATION_CLEANUP_BATCH_SIZE = 100


class DeviceAuthorizationContractMapper:
    """设备授权记录到公开信封的集中映射。"""

    def to_status(
        self,
        record: DeviceAuthorizationStoreRecord,
        *,
        state: DeviceAuthorizationState | None = None,
    ) -> DeviceAuthorizationEnvelope:
        return DeviceAuthorizationEnvelope(
            header=DeviceAuthorizationHeader(enrollment_id=record.enrollment_id),
            detail=DeviceAuthorizationStatusDetail(
                state=state or record.state,
                display_name=record.display_name,
                platform=record.platform,
                public_key_fingerprint=record.public_key_fingerprint,
                interval_seconds=record.poll_interval_seconds,
                expires_at=record.expires_at,
                host_id=record.host_id,
                key_id=record.key_id,
            ),
        )


class CreateDeviceAuthorizationUsecase:
    """创建未绑定最终所有者的短期设备授权。"""

    def __init__(
        self,
        *,
        store: CodexDeviceAuthorizationStorePort,
        digest_service: SensitiveDigestPort,
        signature_verifier: SignatureVerifierPort,
        ttl_seconds: int,
        poll_interval_seconds: int,
        maximum_create_attempts: int,
    ) -> None:
        self._store = store
        self._digest_service = digest_service
        self._signature_verifier = signature_verifier
        self._ttl_seconds = ttl_seconds
        self._poll_interval_seconds = poll_interval_seconds
        self._maximum_create_attempts = maximum_create_attempts

    async def execute(
        self,
        *,
        detail: DeviceAuthorizationCreateDetail,
        verification_uri: str,
        rotation_host_id: UUID | None = None,
        rotation_old_key_id: UUID | None = None,
        owner_subject_id: str | None = None,
    ) -> DeviceAuthorizationEnvelope:
        public_key = self._decode_public_key(detail.public_key_base64)
        fingerprint = hashlib.sha256(public_key).hexdigest()
        self._verify_nonce_proof(
            detail=detail,
            public_key=public_key,
            fingerprint=fingerprint,
        )
        for _attempt in range(self._maximum_create_attempts):
            enrollment_id = uuid4()
            device_code = secrets.token_urlsafe(DEVICE_CODE_RANDOM_BYTES)
            user_code = self._create_user_code()
            now = datetime.now(UTC)
            expires_at = now + timedelta(seconds=self._ttl_seconds)
            record = DeviceAuthorizationStoreRecord(
                enrollment_id=enrollment_id,
                device_code_digest=self._digest_service.digest(device_code),
                user_code_digest=self._digest_service.digest(user_code),
                display_name=detail.display_name,
                platform=detail.platform,
                public_key=public_key,
                public_key_fingerprint=fingerprint,
                requested_key_id=detail.key_id,
                state=DeviceAuthorizationState.PENDING_USER,
                version=DEVICE_AUTHORIZATION_INITIAL_VERSION,
                poll_interval_seconds=self._poll_interval_seconds,
                poll_attempts=0,
                user_code_attempts=0,
                owner_subject_id=owner_subject_id,
                rotation_host_id=rotation_host_id,
                rotation_old_key_id=rotation_old_key_id,
                expires_at=expires_at,
            )
            if await self._store.create(record):
                return DeviceAuthorizationEnvelope(
                    header=DeviceAuthorizationHeader(enrollment_id=enrollment_id),
                    detail=DeviceAuthorizationIssuedDetail(
                        device_code=device_code,
                        user_code=user_code,
                        verification_uri=verification_uri,
                        interval_seconds=self._poll_interval_seconds,
                        expires_at=expires_at,
                    ),
                )
        raise RuntimeError("设备授权唯一代码生成达到重试上限。")

    def _decode_public_key(self, value: str) -> bytes:
        try:
            decoded = base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("设备公钥必须是有效Base64。") from exc
        if len(decoded) != DEVICE_PUBLIC_KEY_LENGTH_BYTES:
            raise ValueError("设备公钥必须是32字节Ed25519公钥。")
        return decoded

    def _create_user_code(self) -> str:
        raw = "".join(
            secrets.choice(USER_CODE_ALPHABET) for _index in range(USER_CODE_RANDOM_LENGTH)
        )
        return "-".join(
            raw[index : index + USER_CODE_GROUP_LENGTH]
            for index in range(0, USER_CODE_RANDOM_LENGTH, USER_CODE_GROUP_LENGTH)
        )

    def _verify_nonce_proof(
        self,
        *,
        detail: DeviceAuthorizationCreateDetail,
        public_key: bytes,
        fingerprint: str,
    ) -> None:
        try:
            signature = base64.b64decode(detail.nonce_signature_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("设备注册nonce签名必须是有效Base64。") from exc
        if len(signature) != ED25519_SIGNATURE_LENGTH_BYTES:
            raise ValueError("设备注册nonce签名长度无效。")
        message = DeviceEnrollmentCanonicalMessage(
            key_id=detail.key_id,
            display_name=detail.display_name,
            platform=detail.platform,
            public_key_fingerprint=fingerprint,
            nonce=detail.nonce,
        )
        if not self._signature_verifier.verify(
            SignatureVerificationRequest(
                algorithm=SignatureAlgorithm.ED25519,
                public_key=public_key,
                message=message.canonical_bytes(),
                signature=signature,
            )
        ):
            raise ValueError("设备注册nonce签名验证失败。")


class PollDeviceAuthorizationUsecase:
    """按 device code 限速轮询设备授权结果。"""

    def __init__(
        self,
        *,
        store: CodexDeviceAuthorizationStorePort,
        maximum_poll_attempts: int,
    ) -> None:
        self._store = store
        self._maximum_poll_attempts = maximum_poll_attempts
        self._mapper = DeviceAuthorizationContractMapper()

    async def execute(
        self,
        *,
        enrollment_id: UUID,
        device_code: str,
    ) -> DeviceAuthorizationEnvelope:
        record = await self._store.read_by_device_code(
            enrollment_id=enrollment_id,
            device_code=device_code,
        )
        if record is None:
            raise self._not_found()
        now = datetime.now(UTC)
        if record.expires_at <= now:
            expired = record.model_copy(
                update={
                    "state": DeviceAuthorizationState.EXPIRED,
                    "version": record.version + 1,
                }
            )
            await self._store.transition(
                enrollment_id=record.enrollment_id,
                expected_version=record.version,
                expected_state=record.state,
                next_record=expired,
            )
            return self._mapper.to_status(expired)
        if record.poll_attempts >= self._maximum_poll_attempts:
            raise HttpFaultException(
                status_code=HTTPStatus.TOO_MANY_REQUESTS,
                error_code=CodexErrorCode.DEVICE_AUTHORIZATION_SLOW_DOWN,
                message="设备授权轮询次数已达到上限。",
            )
        if (
            record.last_poll_at is not None
            and (now - record.last_poll_at).total_seconds() < record.poll_interval_seconds
        ):
            raise HttpFaultException(
                status_code=HTTPStatus.TOO_MANY_REQUESTS,
                error_code=CodexErrorCode.DEVICE_AUTHORIZATION_SLOW_DOWN,
                message="设备授权轮询过于频繁。",
            )
        next_record = record.model_copy(
            update={
                "version": record.version + 1,
                "last_poll_at": now,
                "poll_attempts": record.poll_attempts + 1,
            }
        )
        changed = await self._store.transition(
            enrollment_id=record.enrollment_id,
            expected_version=record.version,
            expected_state=record.state,
            next_record=next_record,
        )
        if changed is None:
            raise HttpFaultException(
                status_code=HTTPStatus.CONFLICT,
                error_code=CodexErrorCode.STATE_CONFLICT,
                message="设备授权状态已发生变化，请重新轮询。",
            )
        return self._mapper.to_status(changed)

    def _not_found(self) -> HttpFaultException:
        return HttpFaultException(
            status_code=HTTPStatus.NOT_FOUND,
            error_code=CodexErrorCode.DEVICE_AUTHORIZATION_NOT_FOUND,
            message="设备授权不存在。",
        )


class ReadDeviceAuthorizationUsecase:
    """浏览器按 user code 读取待批准设备摘要。"""

    def __init__(self, *, store: CodexDeviceAuthorizationStorePort) -> None:
        self._store = store
        self._mapper = DeviceAuthorizationContractMapper()

    async def execute(self, *, user_code: str) -> DeviceAuthorizationEnvelope:
        record = await self._store.read_by_user_code(user_code)
        if record is None:
            raise HttpFaultException(
                status_code=HTTPStatus.NOT_FOUND,
                error_code=CodexErrorCode.DEVICE_AUTHORIZATION_NOT_FOUND,
                message="设备授权代码无效。",
            )
        if record.expires_at <= datetime.now(UTC):
            raise HttpFaultException(
                status_code=HTTPStatus.GONE,
                error_code=CodexErrorCode.DEVICE_AUTHORIZATION_EXPIRED,
                message="设备授权已经过期。",
            )
        return self._mapper.to_status(record)


class DecideDeviceAuthorizationUsecase:
    """通过 Redis CAS 和 PostgreSQL UoW 编排批准 Saga。"""

    def __init__(
        self,
        *,
        store: CodexDeviceAuthorizationStorePort,
        control_port: CodexControlPort,
        key_rotation_grace_seconds: int,
    ) -> None:
        self._store = store
        self._control_port = control_port
        self._key_rotation_grace_seconds = key_rotation_grace_seconds
        self._mapper = DeviceAuthorizationContractMapper()

    async def execute(
        self,
        *,
        request: DeviceAuthorizationDecideRequest,
        owner_subject_id: str,
    ) -> DeviceAuthorizationEnvelope:
        record = await self._store.read_by_user_code(request.user_code)
        if record is None or record.enrollment_id != request.enrollment_id:
            raise self._not_found()
        if record.owner_subject_id is not None and record.owner_subject_id != owner_subject_id:
            raise self._not_found()
        if record.expires_at <= datetime.now(UTC):
            raise self._expired()
        if request.decision == DeviceAuthorizationDecision.DENY:
            return await self._deny(record, request, owner_subject_id)
        return await self._approve(record, request, owner_subject_id)

    async def _deny(
        self,
        record: DeviceAuthorizationStoreRecord,
        request: DeviceAuthorizationDecideRequest,
        owner_subject_id: str,
    ) -> DeviceAuthorizationEnvelope:
        if record.state == DeviceAuthorizationState.DENIED:
            if record.owner_subject_id != owner_subject_id:
                raise self._not_found()
            await asyncio.to_thread(
                self._write_audit,
                record=record,
                request=request,
                owner_subject_id=owner_subject_id,
                host_id=None,
            )
            return self._mapper.to_status(record)
        if record.state != DeviceAuthorizationState.PENDING_USER:
            raise self._state_conflict()
        denied = record.model_copy(
            update={
                "state": DeviceAuthorizationState.DENIED,
                "owner_subject_id": owner_subject_id,
                "version": record.version + 1,
            }
        )
        changed = await self._store.transition(
            enrollment_id=record.enrollment_id,
            expected_version=record.version,
            expected_state=record.state,
            next_record=denied,
        )
        if changed is None:
            raise self._state_conflict()
        await asyncio.to_thread(
            self._write_audit,
            record=changed,
            request=request,
            owner_subject_id=owner_subject_id,
            host_id=None,
        )
        return self._mapper.to_status(changed)

    async def _approve(
        self,
        record: DeviceAuthorizationStoreRecord,
        request: DeviceAuthorizationDecideRequest,
        owner_subject_id: str,
    ) -> DeviceAuthorizationEnvelope:
        if record.state == DeviceAuthorizationState.APPROVED:
            if record.owner_subject_id != owner_subject_id:
                raise self._not_found()
            await self._finalize_approved_identity(record, owner_subject_id)
            return self._mapper.to_status(record)
        if record.state == DeviceAuthorizationState.PENDING_USER:
            approving = record.model_copy(
                update={
                    "state": DeviceAuthorizationState.APPROVING,
                    "owner_subject_id": owner_subject_id,
                    "version": record.version + 1,
                }
            )
            changed = await self._store.transition(
                enrollment_id=record.enrollment_id,
                expected_version=record.version,
                expected_state=record.state,
                next_record=approving,
            )
            if changed is None:
                raise self._state_conflict()
            record = changed
        elif (
            record.state != DeviceAuthorizationState.APPROVING
            or record.owner_subject_id != owner_subject_id
        ):
            raise self._state_conflict()
        host_id, key_id = await asyncio.to_thread(
            self._persist_approved_identity,
            record=record,
            request=request,
            owner_subject_id=owner_subject_id,
        )
        approved = record.model_copy(
            update={
                "state": DeviceAuthorizationState.APPROVED,
                "host_id": host_id,
                "key_id": key_id,
                "version": record.version + 1,
            }
        )
        changed = await self._store.transition(
            enrollment_id=record.enrollment_id,
            expected_version=record.version,
            expected_state=DeviceAuthorizationState.APPROVING,
            next_record=approved,
        )
        if changed is None:
            latest = await self._store.read_by_user_code(request.user_code)
            if (
                latest is not None
                and latest.state == DeviceAuthorizationState.APPROVED
                and latest.host_id == host_id
                and latest.key_id == key_id
            ):
                return self._mapper.to_status(latest)
            raise self._state_conflict()
        await self._finalize_approved_identity(changed, owner_subject_id)
        return self._mapper.to_status(changed)

    async def _finalize_approved_identity(
        self,
        record: DeviceAuthorizationStoreRecord,
        owner_subject_id: str,
    ) -> None:
        try:
            await asyncio.to_thread(
                self._activate_approved_identity,
                record=record,
                owner_subject_id=owner_subject_id,
            )
        except HttpFaultException:
            raise
        except Exception as exc:
            raise HttpFaultException(
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                error_code=CodexErrorCode.DEVICE_AUTHORIZATION_FINALIZATION_PENDING,
                message="设备授权已批准，设备身份激活仍待重试。",
            ) from exc

    def _persist_approved_identity(
        self,
        *,
        record: DeviceAuthorizationStoreRecord,
        request: DeviceAuthorizationDecideRequest,
        owner_subject_id: str,
    ) -> tuple[UUID, UUID]:
        unit_of_work = self._control_port.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            key_repository = self._control_port.create_codex_device_key_repository(session)
            existing_key = key_repository.get_by_enrollment(record.enrollment_id)
            audit_repository = (
                self._control_port.create_codex_device_authorization_audit_repository(session)
            )
            existing_audit = audit_repository.get_by_enrollment_and_idempotency_key(
                enrollment_id=record.enrollment_id,
                idempotency_key=request.idempotency_key,
            )
            if existing_key is not None:
                if existing_key.owner_subject_id != owner_subject_id:
                    raise self._not_found()
                host_id = existing_key.host_id
                key_id = existing_key.key_id
            else:
                now = datetime.now(UTC)
                key_id = record.requested_key_id
                if record.rotation_host_id is not None and record.rotation_old_key_id is not None:
                    host_id = record.rotation_host_id
                    host = self._control_port.create_codex_host_repository(
                        session
                    ).get_by_id_and_owner(host_id, owner_subject_id)
                    old_key = key_repository.get_by_key_and_host(
                        record.rotation_old_key_id,
                        host_id,
                    )
                    if (
                        host is None
                        or host.revoked_at is not None
                        or old_key is None
                        or old_key.owner_subject_id != owner_subject_id
                        or old_key.state
                        not in {
                            DeviceKeyState.ACTIVE,
                            DeviceKeyState.ROTATING,
                        }
                    ):
                        raise self._state_conflict()
                else:
                    host_id = uuid4()
                    self._control_port.create_codex_host_repository(session).add(
                        CodexHostSnapshot(
                            host_id=host_id,
                            owner_subject_id=owner_subject_id,
                            display_name=record.display_name,
                            platform=record.platform,
                            status=CodexHostStatus.OFFLINE.value,
                            created_at=now,
                            updated_at=now,
                            version=1,
                        )
                    )
                    unit_of_work.flush()
                key_repository.add(
                    CodexDeviceKeySnapshot(
                        key_id=key_id,
                        enrollment_id=record.enrollment_id,
                        host_id=host_id,
                        owner_subject_id=owner_subject_id,
                        public_key=record.public_key,
                        fingerprint=record.public_key_fingerprint,
                        state=DeviceKeyState.PENDING,
                        version=1,
                        created_at=now,
                        updated_at=now,
                    )
                )
            if existing_audit is None:
                audit_repository.add(
                    DeviceAuthorizationAuditSnapshot(
                        audit_id=uuid4(),
                        enrollment_id=record.enrollment_id,
                        host_id=host_id,
                        owner_subject_id=owner_subject_id,
                        decision=DeviceAuthorizationDecision.APPROVE,
                        idempotency_key=request.idempotency_key,
                        occurred_at=datetime.now(UTC),
                    )
                )
            unit_of_work.commit()
            return host_id, key_id
        except BaseException:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()

    def _activate_approved_identity(
        self,
        *,
        record: DeviceAuthorizationStoreRecord,
        owner_subject_id: str,
    ) -> None:
        """在 Redis 已批准后激活新 key，并原子迁移旧 key。"""

        if record.host_id is None or record.key_id is None:
            raise self._state_conflict()
        unit_of_work = self._control_port.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            key_repository = self._control_port.create_codex_device_key_repository(session)
            key = key_repository.get_by_key_and_host(record.key_id, record.host_id)
            if key is None or key.owner_subject_id != owner_subject_id:
                raise self._state_conflict()
            now = datetime.now(UTC)
            if key.state == DeviceKeyState.PENDING:
                key_repository.save(
                    key.model_copy(
                        update={
                            "state": DeviceKeyState.ACTIVE,
                            "activated_at": now,
                            "updated_at": now,
                            "version": key.version + 1,
                        }
                    )
                )
            elif key.state != DeviceKeyState.ACTIVE:
                raise self._state_conflict()
            if record.rotation_old_key_id is not None:
                old_key = key_repository.get_by_key_and_host(
                    record.rotation_old_key_id,
                    record.host_id,
                )
                if old_key is None or old_key.owner_subject_id != owner_subject_id:
                    raise self._state_conflict()
                if old_key.state == DeviceKeyState.ACTIVE:
                    key_repository.save(
                        old_key.model_copy(
                            update={
                                "state": DeviceKeyState.ROTATING,
                                "retire_after": now
                                + timedelta(seconds=self._key_rotation_grace_seconds),
                                "updated_at": now,
                                "version": old_key.version + 1,
                            }
                        )
                    )
                elif old_key.state != DeviceKeyState.ROTATING:
                    raise self._state_conflict()
            unit_of_work.commit()
        except BaseException:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()

    def _write_audit(
        self,
        *,
        record: DeviceAuthorizationStoreRecord,
        request: DeviceAuthorizationDecideRequest,
        owner_subject_id: str,
        host_id: UUID | None,
    ) -> None:
        unit_of_work = self._control_port.create_unit_of_work()
        try:
            repository = self._control_port.create_codex_device_authorization_audit_repository(
                unit_of_work.get_session()
            )
            if (
                repository.get_by_enrollment_and_idempotency_key(
                    enrollment_id=record.enrollment_id,
                    idempotency_key=request.idempotency_key,
                )
                is None
            ):
                repository.add(
                    DeviceAuthorizationAuditSnapshot(
                        audit_id=uuid4(),
                        enrollment_id=record.enrollment_id,
                        host_id=host_id,
                        owner_subject_id=owner_subject_id,
                        decision=request.decision,
                        idempotency_key=request.idempotency_key,
                        occurred_at=datetime.now(UTC),
                    )
                )
            unit_of_work.commit()
        except BaseException:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()

    def _not_found(self) -> HttpFaultException:
        return HttpFaultException(
            status_code=HTTPStatus.NOT_FOUND,
            error_code=CodexErrorCode.DEVICE_AUTHORIZATION_NOT_FOUND,
            message="设备授权不存在。",
        )

    def _expired(self) -> HttpFaultException:
        return HttpFaultException(
            status_code=HTTPStatus.GONE,
            error_code=CodexErrorCode.DEVICE_AUTHORIZATION_EXPIRED,
            message="设备授权已经过期。",
        )

    def _state_conflict(self) -> HttpFaultException:
        return HttpFaultException(
            status_code=HTTPStatus.CONFLICT,
            error_code=CodexErrorCode.STATE_CONFLICT,
            message="设备授权状态冲突。",
        )


class CleanupExpiredDeviceAuthorizationsUsecase:
    """撤销长期停留在 pending 的 key，并清理孤立新主机。"""

    def __init__(self, *, control_port: CodexControlPort, pending_ttl_seconds: int) -> None:
        self._control_port = control_port
        self._pending_ttl_seconds = pending_ttl_seconds

    async def execute(self) -> int:
        """按固定批次执行一次幂等清理。"""

        return await asyncio.to_thread(self._cleanup)

    def _cleanup(self) -> int:
        unit_of_work = self._control_port.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            repository = self._control_port.create_codex_device_key_repository(session)
            expired = repository.list_pending_created_before(
                created_before=datetime.now(UTC) - timedelta(seconds=self._pending_ttl_seconds),
                limit=DEVICE_AUTHORIZATION_CLEANUP_BATCH_SIZE,
            )
            now = datetime.now(UTC)
            host_repository = self._control_port.create_codex_host_repository(session)
            for key in expired:
                repository.save(
                    key.model_copy(
                        update={
                            "state": DeviceKeyState.EXPIRED,
                            "revoked_at": now,
                            "updated_at": now,
                            "version": key.version + 1,
                        }
                    )
                )
                host_keys = repository.list_by_host_and_owner(
                    key.host_id,
                    key.owner_subject_id,
                )
                if any(
                    item.key_id != key.key_id
                    and item.state in {DeviceKeyState.ACTIVE, DeviceKeyState.ROTATING}
                    for item in host_keys
                ):
                    continue
                host = host_repository.get_by_id_and_owner(
                    key.host_id,
                    key.owner_subject_id,
                )
                if host is not None and host.revoked_at is None:
                    host_repository.save(
                        host.model_copy(
                            update={
                                "status": CodexHostStatus.REVOKED.value,
                                "revoked_at": now,
                                "updated_at": now,
                                "version": host.version + 1,
                            }
                        )
                    )
            unit_of_work.commit()
            return len(expired)
        except BaseException:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()
