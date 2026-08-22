"""Codex 自助设备授权与公钥挑战路由。"""

from __future__ import annotations

from typing import cast
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Request

from src.api.dependency_context_accessor import DependencyContextAccessor
from src.api.endpoint_codex_control.codex_security_rate_limit import (
    CodexSecurityRateLimitEnforcer,
)
from src.core.codex_contract.codex_runtime_contract import CodexSecurityRateLimitOperation
from src.core.codex_contract.device_authorization_contract import (
    DeviceAuthorizationCreateRequestEnvelope,
    DeviceAuthorizationDecideRequestEnvelope,
    DeviceAuthorizationEnvelope,
    DeviceAuthorizationPollRequestEnvelope,
)
from src.core.codex_contract.device_key_contract import (
    AgentConnectionTicketResponse,
    DeviceChallengeIssue,
    DeviceChallengeIssueRequestEnvelope,
    DeviceChallengeProofRequestEnvelope,
    DeviceKeyRotationStartRequestEnvelope,
)
from src.core.codex_contract.enrollment_intent_contract import (
    CodexEnrollmentIntentConsumeRequestEnvelope,
    CodexEnrollmentIntentCreateRequestEnvelope,
    CodexEnrollmentIntentEnvelope,
)
from src.core.exception_contract.error_code_catalog_contract import SuccessCode
from src.core.http_contract.response_envelope_contract import ResponseEnvelope
from src.domain.codex.codex_authorization_policy import (
    CODEX_HOST_MANAGE_AUTHORIZATION_REQUIREMENT,
)
from src.infrastructure.codex.codex_control_runtime import CodexControlRuntime

DEVICE_VERIFICATION_PATH = "/codex/verify-device"
DEVICE_USER_CODE_PATH_MAXIMUM_LENGTH = 16


class CodexDeviceAuthorizationRouteCatalog:
    """注册公开 Agent 授权流和登录用户批准流。"""

    def __init__(self) -> None:
        self._accessor = DependencyContextAccessor()
        self._rate_limit = CodexSecurityRateLimitEnforcer()
        self.router = APIRouter()
        self.router.add_api_route(
            "/internal/codex-agents/device-authorizations",
            self.create_authorization,
            methods=["POST"],
            response_model=DeviceAuthorizationEnvelope,
        )
        self.router.add_api_route(
            "/internal/codex-agents/device-authorizations/poll",
            self.poll_authorization,
            methods=["POST"],
            response_model=DeviceAuthorizationEnvelope,
        )
        self.router.add_api_route(
            "/internal/codex-agents/enrollment-intents/consume",
            self.consume_enrollment_intent,
            methods=["POST"],
            response_model=DeviceAuthorizationEnvelope,
        )
        self.router.add_api_route(
            "/internal/codex-agents/device-challenges",
            self.issue_challenge,
            methods=["POST"],
            response_model=DeviceChallengeIssue,
        )
        self.router.add_api_route(
            "/internal/codex-agents/connection-tickets",
            self.verify_challenge,
            methods=["POST"],
            response_model=AgentConnectionTicketResponse,
        )
        self.router.add_api_route(
            "/internal/codex-agents/device-key-rotations",
            self.start_key_rotation,
            methods=["POST"],
            response_model=DeviceAuthorizationEnvelope,
        )
        self.router.add_api_route(
            "/codex/device-authorizations/{user_code}",
            self.read_authorization,
            methods=["GET"],
            response_model=ResponseEnvelope[DeviceAuthorizationEnvelope],
            dependencies=[Depends(self.require_host_manage)],
        )
        self.router.add_api_route(
            "/codex/device-authorizations/decisions",
            self.decide_authorization,
            methods=["POST"],
            response_model=ResponseEnvelope[DeviceAuthorizationEnvelope],
            dependencies=[Depends(self.require_host_manage)],
        )
        self.router.add_api_route(
            "/codex/enrollment-intents",
            self.create_enrollment_intent,
            methods=["POST"],
            response_model=ResponseEnvelope[CodexEnrollmentIntentEnvelope],
            dependencies=[Depends(self.require_host_manage)],
        )
        self.router.add_api_route(
            "/codex/enrollment-intents/{intent_id}",
            self.read_enrollment_intent,
            methods=["GET"],
            response_model=ResponseEnvelope[CodexEnrollmentIntentEnvelope],
            dependencies=[Depends(self.require_host_manage)],
        )

    async def require_host_manage(self, request: Request) -> None:
        self._accessor.read_authorized_principal(
            request,
            CODEX_HOST_MANAGE_AUTHORIZATION_REQUIREMENT,
        )

    async def create_authorization(
        self,
        request: Request,
        body: DeviceAuthorizationCreateRequestEnvelope,
    ) -> DeviceAuthorizationEnvelope:
        runtime = self._read_runtime(request)
        self._rate_limit.enforce(
            request=request,
            settings=runtime.settings,
            operation=CodexSecurityRateLimitOperation.DEVICE_AUTHORIZATION_CREATE,
        )
        base_uri = str(request.base_url).rstrip("/")
        return await runtime.create_device_authorization.execute(
            detail=body.detail,
            verification_uri=f"{base_uri}{DEVICE_VERIFICATION_PATH}",
        )

    async def poll_authorization(
        self,
        request: Request,
        body: DeviceAuthorizationPollRequestEnvelope,
    ) -> DeviceAuthorizationEnvelope:
        runtime = self._read_runtime(request)
        self._rate_limit.enforce(
            request=request,
            settings=runtime.settings,
            operation=CodexSecurityRateLimitOperation.DEVICE_AUTHORIZATION_POLL,
            auth_field_values=[str(body.detail.enrollment_id)],
        )
        return await runtime.poll_device_authorization.execute(
            enrollment_id=body.detail.enrollment_id,
            device_code=body.detail.device_code,
        )

    async def consume_enrollment_intent(
        self,
        request: Request,
        body: CodexEnrollmentIntentConsumeRequestEnvelope,
    ) -> DeviceAuthorizationEnvelope:
        """允许 Agent 使用一次性 token 创建设备授权。"""

        return await self._read_runtime(request).manage_enrollment_intent.consume(
            detail=body.detail
        )

    async def issue_challenge(
        self,
        request: Request,
        body: DeviceChallengeIssueRequestEnvelope,
    ) -> DeviceChallengeIssue:
        runtime = self._read_runtime(request)
        self._rate_limit.enforce(
            request=request,
            settings=runtime.settings,
            operation=CodexSecurityRateLimitOperation.DEVICE_CHALLENGE_ISSUE,
            auth_field_values=[str(body.detail.host_id), str(body.detail.key_id)],
        )
        return await runtime.issue_device_challenge.execute(
            host_id=body.detail.host_id,
            key_id=body.detail.key_id,
        )

    async def verify_challenge(
        self,
        request: Request,
        body: DeviceChallengeProofRequestEnvelope,
    ) -> AgentConnectionTicketResponse:
        runtime = self._read_runtime(request)
        self._rate_limit.enforce(
            request=request,
            settings=runtime.settings,
            operation=CodexSecurityRateLimitOperation.DEVICE_CONNECTION_TICKET,
            auth_field_values=[str(body.detail.host_id), str(body.detail.key_id)],
        )
        return await runtime.verify_device_challenge.execute(
            proof=body.detail,
            client_ip=request.client.host if request.client is not None else None,
        )

    async def start_key_rotation(
        self,
        request: Request,
        body: DeviceKeyRotationStartRequestEnvelope,
    ) -> DeviceAuthorizationEnvelope:
        runtime = self._read_runtime(request)
        self._rate_limit.enforce(
            request=request,
            settings=runtime.settings,
            operation=CodexSecurityRateLimitOperation.DEVICE_KEY_ROTATION,
            auth_field_values=[
                str(body.detail.proof.host_id),
                str(body.detail.proof.key_id),
            ],
        )
        base_uri = str(request.base_url).rstrip("/")
        return await runtime.start_device_key_rotation.execute(
            detail=body.detail,
            verification_uri=f"{base_uri}{DEVICE_VERIFICATION_PATH}",
        )

    async def read_authorization(
        self,
        request: Request,
        user_code: str = Path(
            min_length=6,
            max_length=DEVICE_USER_CODE_PATH_MAXIMUM_LENGTH,
        ),
    ) -> ResponseEnvelope[DeviceAuthorizationEnvelope]:
        runtime = self._read_runtime(request)
        self._rate_limit.enforce(
            request=request,
            settings=runtime.settings,
            operation=CodexSecurityRateLimitOperation.DEVICE_AUTHORIZATION_READ,
            auth_field_values=[user_code],
            include_subject=True,
        )
        result = await runtime.read_device_authorization.execute(user_code=user_code)
        return self._accessor.read_response_factory(request).build(
            code=str(SuccessCode.OK),
            message="设备授权读取成功。",
            request_scope=self._accessor.read_request_scope(request),
            data=result,
        )

    async def decide_authorization(
        self,
        request: Request,
        body: DeviceAuthorizationDecideRequestEnvelope,
    ) -> ResponseEnvelope[DeviceAuthorizationEnvelope]:
        runtime = self._read_runtime(request)
        self._rate_limit.enforce(
            request=request,
            settings=runtime.settings,
            operation=CodexSecurityRateLimitOperation.DEVICE_AUTHORIZATION_DECIDE,
            auth_field_values=[str(body.detail.enrollment_id)],
            include_subject=True,
        )
        principal = self._accessor.read_authenticated_principal(request)
        result = await runtime.decide_device_authorization.execute(
            request=body.detail,
            owner_subject_id=principal.subject_id,
        )
        return self._accessor.read_response_factory(request).build(
            code=str(SuccessCode.OK),
            message="设备授权决定已提交。",
            request_scope=self._accessor.read_request_scope(request),
            data=result,
        )

    async def create_enrollment_intent(
        self,
        request: Request,
        body: CodexEnrollmentIntentCreateRequestEnvelope,
    ) -> ResponseEnvelope[CodexEnrollmentIntentEnvelope]:
        """为当前登录会话创建一次性设备注册意图。"""

        principal = self._accessor.read_authenticated_principal(request)
        token_payload = self._accessor.read_access_token_payload(request)
        runtime = self._read_runtime(request)
        result = await runtime.manage_enrollment_intent.create(
            subject_id=principal.subject_id,
            token_session_id=token_payload.token_session_id,
            agent_deployment_profile=runtime.settings.agent_deployment_profile,
            verification_base_url=str(request.base_url).rstrip("/"),
            return_path=body.detail.return_path,
        )
        return self._accessor.read_response_factory(request).build(
            code=str(SuccessCode.OK),
            message="设备注册意图创建成功。",
            request_scope=self._accessor.read_request_scope(request),
            data=result,
        )

    async def read_enrollment_intent(
        self,
        request: Request,
        intent_id: UUID,
    ) -> ResponseEnvelope[CodexEnrollmentIntentEnvelope]:
        """读取当前登录会话创建的设备注册意图。"""

        principal = self._accessor.read_authenticated_principal(request)
        token_payload = self._accessor.read_access_token_payload(request)
        result = await self._read_runtime(request).manage_enrollment_intent.read(
            intent_id=intent_id,
            subject_id=principal.subject_id,
            token_session_id=token_payload.token_session_id,
        )
        return self._accessor.read_response_factory(request).build(
            code=str(SuccessCode.OK),
            message="设备注册意图读取成功。",
            request_scope=self._accessor.read_request_scope(request),
            data=result,
        )

    def _read_runtime(self, request: Request) -> CodexControlRuntime:
        return cast(
            CodexControlRuntime,
            request.app.state.container.resource_mount.get_codex_control_runtime(),
        )
