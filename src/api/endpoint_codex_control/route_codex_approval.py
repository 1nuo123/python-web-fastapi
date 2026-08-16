"""Codex 基础审批产品 REST 路由。"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.api.dependency_context_accessor import DependencyContextAccessor
from src.core.codex_contract.approval_contract import (
    CodexApprovalCollection,
    CodexApprovalDecisionRequest,
)
from src.core.codex_contract.turn_contract import CodexOperationAccepted
from src.core.exception_contract.error_code_catalog_contract import SuccessCode
from src.core.http_contract.response_envelope_contract import ResponseEnvelope
from src.domain.codex.codex_authorization_policy import (
    CODEX_APPROVE_AUTHORIZATION_REQUIREMENT,
)

CODEX_APPROVAL_BEARER_SCHEME = HTTPBearer(auto_error=False)


class CodexApprovalRouteCatalog:
    """注册当前主体审批列表和 CAS 决定接口。"""

    def __init__(self) -> None:
        self._accessor = DependencyContextAccessor()
        self.router = APIRouter()
        self.router.add_api_route(
            "/codex/approvals",
            self.get_approvals,
            methods=["GET"],
            response_model=ResponseEnvelope[CodexApprovalCollection],
            dependencies=[Depends(self.require_codex_approve)],
        )
        self.router.add_api_route(
            "/codex/approvals/{approval_id}/decision",
            self.decide_approval,
            methods=["POST"],
            status_code=status.HTTP_202_ACCEPTED,
            response_model=ResponseEnvelope[CodexOperationAccepted],
            dependencies=[Depends(self.require_codex_approve)],
        )

    async def require_codex_approve(
        self,
        request: Request,
        _credentials: HTTPAuthorizationCredentials | None = Security(CODEX_APPROVAL_BEARER_SCHEME),
    ) -> None:
        self._accessor.read_authorized_principal(
            request,
            CODEX_APPROVE_AUTHORIZATION_REQUIREMENT,
        )

    async def get_approvals(
        self,
        request: Request,
    ) -> ResponseEnvelope[CodexApprovalCollection]:
        principal = self._accessor.read_authenticated_principal(request)
        payload = await self._accessor.read_request_execution_bridge(request).run_sync(
            execution_name="default_sync_usecase",
            callable_object=self._accessor.read_manage_codex_approval_usecase(request).list,
            owner_subject_id=principal.subject_id,
        )
        return self._accessor.read_response_factory(request).build(
            code=str(SuccessCode.OK),
            message="Codex审批列表读取成功。",
            request_scope=self._accessor.read_request_scope(request),
            data=payload,
        )

    async def decide_approval(
        self,
        request: Request,
        approval_id: UUID,
        body: CodexApprovalDecisionRequest,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=256),
        step_up_token: str | None = Header(
            default=None,
            alias="X-Step-Up-Token",
            max_length=512,
        ),
    ) -> ResponseEnvelope[CodexOperationAccepted]:
        principal = self._accessor.read_authenticated_principal(request)
        usecase = self._accessor.read_manage_codex_approval_usecase(request)
        requirement = await self._accessor.read_request_execution_bridge(request).run_sync(
            execution_name="default_sync_usecase",
            callable_object=usecase.read_decision_authorization_requirement,
            approval_id=approval_id,
            owner_subject_id=principal.subject_id,
            decision=body.decision.value,
        )
        self._accessor.read_authorized_principal(request, requirement)
        payload = await usecase.decide(
            approval_id=approval_id,
            approval_version=body.approval_version,
            decision=body.decision,
            actor_subject_id=principal.subject_id,
            idempotency_key=idempotency_key,
            step_up_token=step_up_token,
        )
        return self._accessor.read_response_factory(request).build(
            code=str(SuccessCode.OK),
            message="Codex审批决定已接受。",
            request_scope=self._accessor.read_request_scope(request),
            data=payload,
        )
