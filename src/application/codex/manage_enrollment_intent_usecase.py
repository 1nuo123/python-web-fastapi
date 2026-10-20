"""Codex 已认证设备注册意图用例。"""

from __future__ import annotations

import secrets
import hashlib
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from urllib.parse import quote
from uuid import UUID, uuid4

from src.application.codex.manage_device_authorization_usecase import (
    CreateDeviceAuthorizationUsecase,
    DeviceAuthorizationContractMapper,
)
from src.application.ports.codex_device_authorization_store_port import (
    CodexDeviceAuthorizationStorePort,
)
from src.application.ports.codex_enrollment_intent_store_port import (
    CodexEnrollmentIntentStorePort,
)
from src.application.ports.sensitive_digest_port import SensitiveDigestPort
from src.core.codex_contract.codex_runtime_contract import CodexAgentDeploymentProfile
from src.core.codex_contract.device_authorization_contract import (
    DeviceAuthorizationEnvelope,
    DeviceAuthorizationHeader,
    DeviceAuthorizationIssuedDetail,
)
from src.core.codex_contract.enrollment_intent_contract import (
    CodexEnrollmentIntentConsumeDetail,
    CodexEnrollmentIntentEnvelope,
    CodexEnrollmentIntentHeader,
    CodexEnrollmentIntentIssuedDetail,
    CodexEnrollmentIntentState,
    CodexEnrollmentIntentStatusDetail,
    CodexEnrollmentIntentStoreRecord,
)
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.domain.codex.codex_error_code import CodexErrorCode

CODEX_ENROLLMENT_INTENT_INITIAL_VERSION = 1
CODEX_ENROLLMENT_INTENT_TOKEN_BYTES = 32


class ManageCodexEnrollmentIntentUsecase:
    """创建、消费和读取绑定登录会话的一次性注册意图。"""

    def __init__(
        self,
        *,
        store: CodexEnrollmentIntentStorePort,
        device_authorization_store: CodexDeviceAuthorizationStorePort,
        create_device_authorization: CreateDeviceAuthorizationUsecase,
        digest_service: SensitiveDigestPort,
        ttl_seconds: int,
        maximum_create_attempts: int,
    ) -> None:
        self._store = store
        self._device_authorization_store = device_authorization_store
        self._create_device_authorization = create_device_authorization
        self._digest_service = digest_service
        self._ttl_seconds = ttl_seconds
        self._maximum_create_attempts = maximum_create_attempts
        self._authorization_mapper = DeviceAuthorizationContractMapper()

    async def create(
        self,
        *,
        subject_id: str,
        token_session_id: UUID,
        agent_deployment_profile: CodexAgentDeploymentProfile,
        verification_base_url: str,
        return_path: str,
    ) -> CodexEnrollmentIntentEnvelope:
        """创建短时注册意图，URI 只携带一次性 token。"""

        for _attempt in range(self._maximum_create_attempts):
            intent_id = uuid4()
            intent_token = secrets.token_urlsafe(CODEX_ENROLLMENT_INTENT_TOKEN_BYTES)
            expires_at = datetime.now(UTC) + timedelta(seconds=self._ttl_seconds)
            verification_uri = (
                f"{verification_base_url.rstrip('/')}{return_path}"
                f"?intent_id={quote(str(intent_id), safe='')}"
            )
            record = CodexEnrollmentIntentStoreRecord(
                intent_id=intent_id,
                token_digest=self._digest_service.digest(intent_token),
                subject_id=subject_id,
                token_session_id=token_session_id,
                verification_uri=verification_uri,
                state=CodexEnrollmentIntentState.ISSUED,
                version=CODEX_ENROLLMENT_INTENT_INITIAL_VERSION,
                expires_at=expires_at,
            )
            if await self._store.create(record):
                return CodexEnrollmentIntentEnvelope(
                    header=CodexEnrollmentIntentHeader(intent_id=intent_id),
                    detail=CodexEnrollmentIntentIssuedDetail(
                        state=CodexEnrollmentIntentState.ISSUED,
                        launch_uri=(
                            f"{agent_deployment_profile.enrollment_uri_scheme}://enroll"
                            f"?token={quote(intent_token, safe='')}"
                        ),
                        expires_at=expires_at,
                    ),
                )
        raise RuntimeError("设备注册意图唯一token生成达到重试上限。")

    async def consume(
        self,
        *,
        detail: CodexEnrollmentIntentConsumeDetail,
    ) -> DeviceAuthorizationEnvelope:
        """消费一次性 token 并创建已绑定所有者的设备授权。"""

        current = await self._store.read_by_token(detail.intent_token)
        if current is None:
            raise self._not_found()
        request_digest = hashlib.sha256(detail.authorization.model_dump_json().encode()).hexdigest()
        if current.request_digest is not None and current.request_digest != request_digest:
            raise self._conflict()
        if current.state == CodexEnrollmentIntentState.CONSUMED:
            if current.request_digest != request_digest:
                raise self._conflict()
            return self._build_issued_authorization(current)
        self._ensure_not_expired(current)
        if current.state not in {
            CodexEnrollmentIntentState.ISSUED,
            CodexEnrollmentIntentState.CONSUMING,
        }:
            raise self._conflict()
        consuming = current.model_copy(
            update={
                "state": CodexEnrollmentIntentState.CONSUMING,
                "version": current.version + 1,
                "request_digest": request_digest,
            }
        )
        claimed = (
            current
            if current.state == CodexEnrollmentIntentState.CONSUMING
            else await self._store.transition(
                intent_id=current.intent_id,
                expected_version=current.version,
                expected_state=CodexEnrollmentIntentState.ISSUED,
                next_record=consuming,
            )
        )
        if claimed is None:
            raise self._conflict()
        try:
            authorization = await self._create_device_authorization.execute(
                detail=detail.authorization,
                verification_uri=claimed.verification_uri,
                owner_subject_id=claimed.subject_id,
            )
            issued = authorization.detail
            if not isinstance(issued, DeviceAuthorizationIssuedDetail):
                raise RuntimeError("设备授权创建未返回用户代码。")
            consumed = claimed.model_copy(
                update={
                    "state": CodexEnrollmentIntentState.CONSUMED,
                    "version": claimed.version + 1,
                    "enrollment_id": authorization.header.enrollment_id,
                    "user_code": issued.user_code,
                    "device_code": issued.device_code,
                    "poll_interval_seconds": issued.interval_seconds,
                    "authorization_expires_at": issued.expires_at,
                }
            )
            changed = await self._store.transition(
                intent_id=claimed.intent_id,
                expected_version=claimed.version,
                expected_state=CodexEnrollmentIntentState.CONSUMING,
                next_record=consumed,
            )
            if changed is None:
                raise self._conflict()
            return authorization
        except BaseException:
            await self._store.transition(
                intent_id=claimed.intent_id,
                expected_version=claimed.version,
                expected_state=CodexEnrollmentIntentState.CONSUMING,
                next_record=claimed.model_copy(
                    update={
                        "state": CodexEnrollmentIntentState.ISSUED,
                        "version": claimed.version + 1,
                    }
                ),
            )
            raise

    async def read(
        self,
        *,
        intent_id: UUID,
        subject_id: str,
        token_session_id: UUID,
    ) -> CodexEnrollmentIntentEnvelope:
        """仅允许创建该意图的登录会话读取状态。"""

        record = await self._store.read_by_id(intent_id)
        if (
            record is None
            or record.subject_id != subject_id
            or record.token_session_id != token_session_id
        ):
            raise self._not_found()
        if record.state != CodexEnrollmentIntentState.CONSUMED:
            self._ensure_not_expired(record)
        return await self._build_status(record)

    async def resume(
        self, *, intent_token: str, host_id: UUID, key_id: UUID, owner_subject_id: str
    ) -> CodexEnrollmentIntentEnvelope:
        """仅由已验证设备身份完成同账号意图，不创建第二个主机。"""
        current = await self._store.read_by_token(intent_token)
        if current is None or current.subject_id != owner_subject_id:
            raise self._not_found()
        self._ensure_not_expired(current)
        if current.state == CodexEnrollmentIntentState.CONSUMED and current.host_id == host_id:
            return await self._build_status(current)
        if current.state != CodexEnrollmentIntentState.ISSUED and current.enrollment_id != key_id:
            raise self._conflict()
        changed = await self._store.transition(
            intent_id=current.intent_id,
            expected_version=current.version,
            expected_state=current.state,
            next_record=current.model_copy(
                update={
                    "state": CodexEnrollmentIntentState.CONSUMED,
                    "host_id": host_id,
                    "version": current.version + 1,
                }
            ),
        )
        if changed is None:
            raise self._conflict()
        return await self._build_status(changed)

    async def _build_status(
        self,
        record: CodexEnrollmentIntentStoreRecord,
    ) -> CodexEnrollmentIntentEnvelope:
        authorization = None
        if record.user_code is not None:
            authorization_record = await self._device_authorization_store.read_by_user_code(
                record.user_code
            )
            if authorization_record is not None:
                authorization = self._authorization_mapper.to_status(authorization_record)
        return CodexEnrollmentIntentEnvelope(
            header=CodexEnrollmentIntentHeader(intent_id=record.intent_id),
            detail=CodexEnrollmentIntentStatusDetail(
                state=record.state,
                expires_at=record.expires_at,
                user_code=record.user_code,
                authorization=authorization,
                host_id=record.host_id,
            ),
        )

    def _build_issued_authorization(
        self,
        record: CodexEnrollmentIntentStoreRecord,
    ) -> DeviceAuthorizationEnvelope:
        if (
            record.enrollment_id is None
            or record.user_code is None
            or record.device_code is None
            or record.poll_interval_seconds is None
        ):
            raise self._conflict()
        return DeviceAuthorizationEnvelope(
            header=DeviceAuthorizationHeader(enrollment_id=record.enrollment_id),
            detail=DeviceAuthorizationIssuedDetail(
                device_code=record.device_code,
                user_code=record.user_code,
                verification_uri=record.verification_uri,
                interval_seconds=record.poll_interval_seconds,
                expires_at=record.authorization_expires_at or record.expires_at,
            ),
        )

    def _ensure_not_expired(self, record: CodexEnrollmentIntentStoreRecord) -> None:
        if record.expires_at <= datetime.now(UTC):
            raise HttpFaultException(
                status_code=HTTPStatus.GONE,
                error_code=CodexErrorCode.ENROLLMENT_INTENT_EXPIRED,
                message="设备注册意图已经过期。",
            )

    def _not_found(self) -> HttpFaultException:
        return HttpFaultException(
            status_code=HTTPStatus.NOT_FOUND,
            error_code=CodexErrorCode.ENROLLMENT_INTENT_NOT_FOUND,
            message="设备注册意图不存在。",
        )

    def _conflict(self) -> HttpFaultException:
        return HttpFaultException(
            status_code=HTTPStatus.CONFLICT,
            error_code=CodexErrorCode.STATE_CONFLICT,
            message="设备注册意图状态冲突。",
        )
