"""Codex 主机元数据与 Agent 发布信息路由。"""

from __future__ import annotations

import asyncio
from typing import TypeVar

from fastapi import APIRouter, Depends, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from src.api.dependency_context_accessor import DependencyContextAccessor
from src.api.web_bundle_catalog import (
    WebBundleProvider,
    WebBundleProviderDetail,
    WebBundleProviderEnvelope,
    WebBundleProviderHeader,
)
from src.application.codex.list_hosts_usecase import ListAllCodexHostsUsecase
from src.core.codex_contract.agent_release_manifest_contract import (
    CodexAgentReleaseDownloadDetail,
    CodexAgentReleaseDownloadEnvelope,
    CodexAgentReleaseManifestHeader,
)
from src.core.codex_contract.host_contract import CodexHostCollection
from src.core.exception_contract.error_code_catalog_contract import SuccessCode
from src.core.http_contract.response_envelope_contract import ResponseEnvelope
from src.core.http_contract.web_bundle_contract import ApplicationModuleName, WebBundle
from src.domain.codex.codex_admin_authorization_policy import (
    CODEX_ADMIN_MANAGE_AUTHORIZATION_REQUIREMENT,
)

CODEX_ADMIN_ROUTE_TAG = "codex_admin"
CODEX_ADMIN_BEARER_SCHEME = HTTPBearer(auto_error=False)
CodexAdminResponsePayloadT = TypeVar("CodexAdminResponsePayloadT", bound=BaseModel)


class CodexAdminRouteCatalog:
    """注册独立 Codex 管理控制面。"""

    def __init__(self) -> None:
        self._accessor = DependencyContextAccessor()
        self.router = APIRouter(tags=[CODEX_ADMIN_ROUTE_TAG])
        self.router.add_api_route(
            "/admin/codex/hosts",
            self.list_hosts,
            methods=["GET"],
            response_model=ResponseEnvelope[CodexHostCollection],
            dependencies=[Depends(self.require_codex_admin_manage)],
        )
        self.router.add_api_route(
            "/codex/agent-release/current",
            self.read_current_agent_release,
            methods=["GET"],
            response_model=ResponseEnvelope[CodexAgentReleaseDownloadEnvelope],
        )

    async def require_codex_admin_manage(
        self,
        request: Request,
        _credentials: HTTPAuthorizationCredentials | None = Security(CODEX_ADMIN_BEARER_SCHEME),
    ) -> None:
        self._accessor.read_authorized_principal(
            request,
            CODEX_ADMIN_MANAGE_AUTHORIZATION_REQUIREMENT,
        )

    async def list_hosts(self, request: Request) -> ResponseEnvelope[CodexHostCollection]:
        payload = await asyncio.to_thread(self._read_host_usecase(request).execute)
        return self._response(request, payload, "Codex主机元数据读取成功。")

    async def read_current_agent_release(
        self,
        request: Request,
        _credentials: HTTPAuthorizationCredentials | None = Security(CODEX_ADMIN_BEARER_SCHEME),
    ) -> ResponseEnvelope[CodexAgentReleaseDownloadEnvelope]:
        """返回登录用户可用的签名安装包与 TUF 清单入口。"""

        self._accessor.read_authenticated_principal(request)
        settings = request.app.state.container.resource_mount.get_codex_control_runtime().settings
        payload = CodexAgentReleaseDownloadEnvelope(
            header=CodexAgentReleaseManifestHeader(),
            detail=CodexAgentReleaseDownloadDetail(
                version=settings.agent_release_version,
                download_url=settings.agent_release_download_url,
                manifest_url=settings.agent_release_manifest_url,
                minimum_security_version=settings.agent_release_minimum_security_version,
            ),
        )
        return self._response(request, payload, "Codex Agent当前版本读取成功。")

    def _read_host_usecase(self, request: Request) -> ListAllCodexHostsUsecase:
        runtime = request.app.state.container.resource_mount.get_codex_control_runtime()
        return ListAllCodexHostsUsecase(control_port=runtime.control_port)

    def _response(
        self,
        request: Request,
        payload: CodexAdminResponsePayloadT,
        message: str,
    ) -> ResponseEnvelope[CodexAdminResponsePayloadT]:
        return self._accessor.read_response_factory(request).build(
            code=str(SuccessCode.OK),
            message=message,
            request_scope=self._accessor.read_request_scope(request),
            data=payload,
        )


class CodexAdminBundleProvider(WebBundleProvider):
    """Codex 管理控制面模块提供者。"""

    module_name = ApplicationModuleName.CODEX_ADMIN.value

    def provide(self) -> WebBundleProviderEnvelope:
        return WebBundleProviderEnvelope(
            header=WebBundleProviderHeader(module_name=self.module_name),
            detail=WebBundleProviderDetail(provider_name=self.__class__.__name__),
            bundle=WebBundle(
                module_name=self.module_name,
                router=CodexAdminRouteCatalog().router,
            ),
        )
