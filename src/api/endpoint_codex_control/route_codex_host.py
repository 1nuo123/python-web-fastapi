"""Codex 主机路由与模块提供者。"""

from __future__ import annotations

from http import HTTPStatus
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.api.dependency_context_accessor import DependencyContextAccessor
from src.api.endpoint_codex_control.codex_security_rate_limit import (
    CodexSecurityRateLimitEnforcer,
)
from src.api.endpoint_codex_control.route_codex_approval import CodexApprovalRouteCatalog
from src.api.endpoint_codex_control.route_codex_device_authorization import (
    CodexDeviceAuthorizationRouteCatalog,
)
from src.api.endpoint_codex_control.route_codex_diagnostic import CodexDiagnosticRouteCatalog
from src.api.endpoint_codex_control.route_codex_realtime import CodexRealtimeRouteCatalog
from src.api.endpoint_codex_control.route_codex_thread import CodexThreadRouteCatalog
from src.api.endpoint_codex_control.route_codex_workspace import CodexWorkspaceRouteCatalog
from src.api.web_bundle_catalog import (
    WebBundleProvider,
    WebBundleProviderDetail,
    WebBundleProviderEnvelope,
    WebBundleProviderHeader,
)
from src.core.codex_contract.agent_enrollment_contract import (
    CodexPairingCodeRequest,
    CodexPairingCodeResponse,
)
from src.core.codex_contract.codex_runtime_contract import CodexSecurityRateLimitOperation
from src.core.codex_contract.feature_flags_contract import CodexExperienceFeatureFlags
from src.core.codex_contract.active_host_contract import (
    CodexActiveHostState,
    CodexActiveHostSwitchRequest,
)
from src.core.codex_contract.host_contract import (
    CodexHostCollection,
    CodexHostRenameRequest,
    CodexHostRevokeRequest,
    CodexHostSnapshot,
)
from src.core.exception_contract.error_code_catalog_contract import SuccessCode
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.http_contract.response_envelope_contract import ResponseEnvelope
from src.core.http_contract.web_bundle_contract import ApplicationModuleName, WebBundle
from src.domain.codex.codex_authorization_policy import (
    CODEX_HOST_MANAGE_AUTHORIZATION_REQUIREMENT,
    CODEX_READ_AUTHORIZATION_REQUIREMENT,
)
from src.domain.codex.codex_error_code import CodexErrorCode

CODEX_ROUTE_TAG = "codex"
CODEX_HOST_BEARER_SCHEME = HTTPBearer(auto_error=False)


class CodexHostRouteCatalog:
    """组合 Codex 控制面首批所有权接口。"""

    def __init__(self) -> None:
        self._accessor = DependencyContextAccessor()
        self._rate_limit = CodexSecurityRateLimitEnforcer()
        self.router = APIRouter(tags=[CODEX_ROUTE_TAG])
        self.router.add_api_route(
            "/codex/active-host",
            self.get_active_host,
            methods=["GET"],
            response_model=ResponseEnvelope[CodexActiveHostState],
            dependencies=[Depends(self.require_codex_read)],
        )
        self.router.add_api_route(
            "/codex/active-host",
            self.switch_active_host,
            methods=["PUT"],
            response_model=ResponseEnvelope[CodexActiveHostState],
            dependencies=[Depends(self.require_codex_host_manage)],
        )
        self.router.add_api_route(
            "/codex/hosts",
            self.get_hosts,
            methods=["GET"],
            response_model=ResponseEnvelope[CodexHostCollection],
            dependencies=[Depends(self.require_codex_read)],
        )
        self.router.add_api_route(
            "/codex/experience/feature-flags",
            self.get_feature_flags,
            methods=["GET"],
            response_model=ResponseEnvelope[CodexExperienceFeatureFlags],
            dependencies=[Depends(self.require_codex_read)],
        )
        self.router.add_api_route(
            "/codex/hosts/{host_id}",
            self.rename_host,
            methods=["PATCH"],
            response_model=ResponseEnvelope[CodexHostSnapshot],
            dependencies=[Depends(self.require_codex_host_manage)],
        )
        self.router.add_api_route(
            "/codex/hosts/{host_id}/revoke",
            self.revoke_host,
            methods=["POST"],
            response_model=ResponseEnvelope[CodexHostSnapshot],
            dependencies=[Depends(self.require_codex_host_manage)],
        )
        self.router.add_api_route(
            "/codex/hosts/pairing-codes",
            self.create_pairing_code,
            methods=["POST"],
            response_model=ResponseEnvelope[CodexPairingCodeResponse],
            dependencies=[Depends(self.require_codex_host_manage)],
        )
        self.router.include_router(CodexWorkspaceRouteCatalog().router)
        self.router.include_router(CodexThreadRouteCatalog().router)
        self.router.include_router(CodexRealtimeRouteCatalog().router)
        self.router.include_router(CodexApprovalRouteCatalog().router)
        self.router.include_router(CodexDeviceAuthorizationRouteCatalog().router)
        self.router.include_router(CodexDiagnosticRouteCatalog().router)

    async def require_codex_read(
        self,
        request: Request,
        _credentials: HTTPAuthorizationCredentials | None = Security(CODEX_HOST_BEARER_SCHEME),
    ) -> None:
        self._accessor.read_authorized_principal(request, CODEX_READ_AUTHORIZATION_REQUIREMENT)

    async def require_codex_host_manage(
        self,
        request: Request,
        _credentials: HTTPAuthorizationCredentials | None = Security(CODEX_HOST_BEARER_SCHEME),
    ) -> None:
        self._accessor.read_authorized_principal(
            request,
            CODEX_HOST_MANAGE_AUTHORIZATION_REQUIREMENT,
        )

    async def create_pairing_code(
        self,
        request: Request,
        body: CodexPairingCodeRequest,
    ) -> ResponseEnvelope[CodexPairingCodeResponse]:
        principal = self._accessor.read_authenticated_principal(request)
        runtime = request.app.state.container.resource_mount.get_codex_control_runtime()
        if not runtime.settings.allow_legacy_agent_bearer:
            raise HttpFaultException(
                status_code=HTTPStatus.GONE,
                error_code=CodexErrorCode.STATE_CONFLICT,
                message="旧版Codex配对码已经停用。",
            )
        issue = await self._accessor.read_request_execution_bridge(request).run_sync(
            execution_name="default_sync_usecase",
            callable_object=request.app.state.container.resource_mount.get_codex_control_runtime().pairing_service.issue,
            owner_subject_id=principal.subject_id,
            display_name=body.display_name,
            platform=body.platform,
        )
        return self._accessor.read_response_factory(request).build(
            code=str(SuccessCode.OK),
            message="Codex配对码已生成。",
            request_scope=self._accessor.read_request_scope(request),
            data=CodexPairingCodeResponse(
                host_id=issue.host_id,
                pairing_code=issue.pairing_code,
                expires_at=issue.expires_at,
            ),
        )

    async def get_active_host(self, request: Request) -> ResponseEnvelope[CodexActiveHostState]:
        principal = self._accessor.read_authenticated_principal(request)
        runtime = request.app.state.container.resource_mount.get_codex_control_runtime()
        state = await runtime.active_host.read(principal.subject_id)
        return self._accessor.read_response_factory(request).build(
            code=str(SuccessCode.OK),
            message="当前连接状态",
            request_scope=self._accessor.read_request_scope(request),
            data=state,
        )

    async def switch_active_host(
        self, request: Request, body: CodexActiveHostSwitchRequest
    ) -> ResponseEnvelope[CodexActiveHostState]:
        principal = self._accessor.read_authenticated_principal(request)
        runtime = request.app.state.container.resource_mount.get_codex_control_runtime()
        state = await runtime.active_host.switch(
            principal.subject_id, body.host_id, body.expected_version
        )
        if state.draining_host_id is not None:
            await runtime.publish_host_status_changed(
                owner_subject_id=principal.subject_id,
                host_id=state.draining_host_id,
                status="offline",
                last_seen_at=None,
            )
        return self._accessor.read_response_factory(request).build(
            code=str(SuccessCode.OK),
            message="连接切换已受理；旧电脑停止后才启用目标电脑。",
            request_scope=self._accessor.read_request_scope(request),
            data=state,
        )

    async def get_hosts(self, request: Request) -> ResponseEnvelope[CodexHostCollection]:
        """读取当前主体拥有的主机。"""

        principal = self._accessor.read_authenticated_principal(request)
        runtime = request.app.state.container.resource_mount.get_codex_control_runtime()
        payload = await self._accessor.read_request_execution_bridge(request).run_sync(
            execution_name="default_sync_usecase",
            callable_object=self._accessor.read_list_codex_hosts_usecase(request).execute,
            owner_subject_id=principal.subject_id,
        )
        active = await runtime.active_host.read(principal.subject_id)
        present_host_ids = await runtime.presence_adapter.list_present(
            [host.host_id for host in payload.items]
        )
        payload = self._accessor.read_list_codex_hosts_usecase(request).overlay_runtime_status(
            payload,
            present_host_ids=present_host_ids.intersection({active.active_host_id}),
            offline_after_seconds=runtime.settings.agent_offline_after_seconds,
        )
        return self._accessor.read_response_factory(request).build(
            code=str(SuccessCode.OK),
            message="Codex 主机读取成功。",
            request_scope=self._accessor.read_request_scope(request),
            data=payload,
        )

    async def get_feature_flags(
        self,
        request: Request,
    ) -> ResponseEnvelope[CodexExperienceFeatureFlags]:
        """返回当前服务端批准的体验开关，浏览器不得单方面开启新路径。"""

        self._accessor.read_authenticated_principal(request)
        runtime = request.app.state.container.resource_mount.get_codex_control_runtime()
        settings = runtime.settings
        flags = CodexExperienceFeatureFlags(
            codex_scroll_controller_v2=settings.codex_scroll_controller_v2,
            codex_realtime_batch_v2=settings.codex_realtime_batch_v2,
            codex_authority_recovery_v2=settings.codex_authority_recovery_v2,
        )
        runtime.record_experience_feature_flag_decisions(flags)
        return self._accessor.read_response_factory(request).build(
            code=str(SuccessCode.OK),
            message="Codex体验开关读取成功。",
            request_scope=self._accessor.read_request_scope(request),
            data=flags,
        )

    async def rename_host(
        self,
        request: Request,
        host_id: UUID,
        body: CodexHostRenameRequest,
        if_match: str = Header(alias="If-Match"),
    ) -> ResponseEnvelope[CodexHostSnapshot]:
        principal = self._accessor.read_authenticated_principal(request)
        runtime = request.app.state.container.resource_mount.get_codex_control_runtime()
        renamed = await runtime.rename_host.execute(
            host_id=host_id,
            owner_subject_id=principal.subject_id,
            display_name=body.display_name,
            expected_version=self._parse_if_match(if_match),
        )
        return self._accessor.read_response_factory(request).build(
            code=str(SuccessCode.OK),
            message="Codex主机已重命名。",
            request_scope=self._accessor.read_request_scope(request),
            data=renamed,
        )

    async def revoke_host(
        self,
        request: Request,
        host_id: UUID,
        body: CodexHostRevokeRequest,
        if_match: str = Header(alias="If-Match"),
    ) -> ResponseEnvelope[CodexHostSnapshot]:
        principal = self._accessor.read_authenticated_principal(request)
        runtime = request.app.state.container.resource_mount.get_codex_control_runtime()
        self._rate_limit.enforce(
            request=request,
            settings=runtime.settings,
            operation=CodexSecurityRateLimitOperation.HOST_REVOKE,
            auth_field_values=[str(host_id)],
            include_subject=True,
        )
        revoked = await runtime.revoke_host.execute(
            host_id=host_id,
            owner_subject_id=principal.subject_id,
            expected_version=self._parse_if_match(if_match),
            step_up_token=body.step_up_token,
        )
        await runtime.active_host.revoke(principal.subject_id, host_id)
        return self._accessor.read_response_factory(request).build(
            code=str(SuccessCode.OK),
            message="Codex主机已撤销。",
            request_scope=self._accessor.read_request_scope(request),
            data=revoked,
        )

    def _parse_if_match(self, value: str) -> int:
        normalized = value.strip().strip('"')
        try:
            version = int(normalized)
        except ValueError as exc:
            raise HttpFaultException(
                status_code=HTTPStatus.BAD_REQUEST,
                error_code=CodexErrorCode.VERSION_CONFLICT,
                message="If-Match必须是主机版本号。",
            ) from exc
        if version < 1:
            raise HttpFaultException(
                status_code=HTTPStatus.BAD_REQUEST,
                error_code=CodexErrorCode.VERSION_CONFLICT,
                message="If-Match主机版本号必须大于零。",
            )
        return version


class CodexControlBundleProvider(WebBundleProvider):
    """Codex 用户控制面模块提供者。"""

    module_name = ApplicationModuleName.CODEX_CONTROL.value

    def provide(self) -> WebBundleProviderEnvelope:
        return WebBundleProviderEnvelope(
            header=WebBundleProviderHeader(module_name=self.module_name),
            detail=WebBundleProviderDetail(provider_name=self.__class__.__name__),
            bundle=WebBundle(
                module_name=self.module_name,
                router=CodexHostRouteCatalog().router,
            ),
        )
