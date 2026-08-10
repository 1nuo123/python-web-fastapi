"""Codex 工作区路由。"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.api.dependency_context_accessor import DependencyContextAccessor
from src.core.codex_contract.workspace_contract import (
    CodexWorkspaceCollection,
    CodexWorkspaceSnapshot,
    CodexWorkspaceUpdateRequest,
)
from src.core.exception_contract.error_code_catalog_contract import SuccessCode
from src.core.http_contract.response_envelope_contract import ResponseEnvelope
from src.domain.codex.codex_authorization_policy import (
    CODEX_HOST_MANAGE_AUTHORIZATION_REQUIREMENT,
    CODEX_READ_AUTHORIZATION_REQUIREMENT,
)

CODEX_BEARER_SCHEME = HTTPBearer(auto_error=False)


class CodexWorkspaceRouteCatalog:
    """注册所有权过滤的工作区读取接口。"""

    def __init__(self) -> None:
        self._accessor = DependencyContextAccessor()
        self.router = APIRouter()
        self.router.add_api_route(
            "/codex/hosts/{host_id}/workspaces",
            self.get_workspaces,
            methods=["GET"],
            response_model=ResponseEnvelope[CodexWorkspaceCollection],
            dependencies=[Depends(self.require_codex_read)],
        )
        self.router.add_api_route(
            "/codex/hosts/{host_id}/workspaces/{workspace_id}",
            self.update_workspace,
            methods=["PATCH"],
            response_model=ResponseEnvelope[CodexWorkspaceSnapshot],
            dependencies=[Depends(self.require_codex_host_manage)],
        )

    async def require_codex_read(
        self,
        request: Request,
        _credentials: HTTPAuthorizationCredentials | None = Security(CODEX_BEARER_SCHEME),
    ) -> None:
        """校验用户认证与 codex:read scope。"""

        self._accessor.read_authorized_principal(request, CODEX_READ_AUTHORIZATION_REQUIREMENT)

    async def require_codex_host_manage(
        self,
        request: Request,
        _credentials: HTTPAuthorizationCredentials | None = Security(CODEX_BEARER_SCHEME),
    ) -> None:
        """校验用户认证与 codex:host:manage scope。"""

        self._accessor.read_authorized_principal(
            request,
            CODEX_HOST_MANAGE_AUTHORIZATION_REQUIREMENT,
        )

    async def get_workspaces(
        self,
        request: Request,
        host_id: UUID,
    ) -> ResponseEnvelope[CodexWorkspaceCollection]:
        """读取当前主体拥有的指定主机工作区。"""

        principal = self._accessor.read_authenticated_principal(request)
        payload = await self._accessor.read_request_execution_bridge(request).run_sync(
            execution_name="default_sync_usecase",
            callable_object=self._accessor.read_list_codex_workspaces_usecase(request).execute,
            host_id=host_id,
            owner_subject_id=principal.subject_id,
        )
        return self._accessor.read_response_factory(request).build(
            code=str(SuccessCode.OK),
            message="Codex 工作区读取成功。",
            request_scope=self._accessor.read_request_scope(request),
            data=payload,
        )

    async def update_workspace(
        self,
        request: Request,
        host_id: UUID,
        workspace_id: UUID,
        body: CodexWorkspaceUpdateRequest,
    ) -> ResponseEnvelope[CodexWorkspaceSnapshot]:
        """更新当前主体拥有的工作区隔离策略。"""

        principal = self._accessor.read_authenticated_principal(request)
        payload = await self._accessor.read_request_execution_bridge(request).run_sync(
            execution_name="default_sync_usecase",
            callable_object=self._accessor.read_update_codex_workspace_usecase(request).execute,
            host_id=host_id,
            workspace_id=workspace_id,
            owner_subject_id=principal.subject_id,
            request=body,
        )
        return self._accessor.read_response_factory(request).build(
            code=str(SuccessCode.OK),
            message="Codex 工作区更新成功。",
            request_scope=self._accessor.read_request_scope(request),
            data=payload,
        )
