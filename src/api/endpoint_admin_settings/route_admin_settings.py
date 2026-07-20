"""
管理员配置热更新路由。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.api.dependency_context_accessor import DependencyContextAccessor
from src.api.endpoint_admin_settings.contract_admin_settings import (
    AdminSettingsReloadCandidateEnvelope,
    AdminSettingsReloadCandidatePayload,
    AdminSettingsReloadHeader,
    AdminSettingsReloadKind,
    AdminSettingsReloadOperationName,
    AdminSettingsReloadRequestEnvelope,
    AdminSettingsReloadResultEnvelope,
    AdminSettingsReloadResultPayload,
)
from src.api.web_bundle_catalog import (
    WebBundleProvider,
    WebBundleProviderDetail,
    WebBundleProviderEnvelope,
    WebBundleProviderHeader,
)
from src.core.exception_contract.error_code_catalog_contract import SuccessCode
from src.core.http_contract.request_execution_contract import (
    DEFAULT_SYNC_REQUEST_EXECUTION_NAME,
)
from src.core.http_contract.response_envelope_contract import ResponseEnvelope
from src.core.http_contract.web_bundle_contract import ApplicationModuleName, WebBundle
from src.domain.auth.admin_route_authorization_policy import (
    ADMIN_SETTINGS_RELOAD_AUTHORIZATION_REQUIREMENT,
)

ADMIN_SETTINGS_ROUTE_TAG = "admin_settings"
ADMIN_SETTINGS_RELOAD_CANDIDATE_PATH = "/admin/settings/reload/candidate"
ADMIN_SETTINGS_RELOAD_PATH = "/admin/settings/reload"
ADMIN_SETTINGS_METHOD_GET = "GET"
ADMIN_SETTINGS_METHOD_POST = "POST"
ADMIN_SETTINGS_REQUEST_EXECUTION_NAME = DEFAULT_SYNC_REQUEST_EXECUTION_NAME
ADMIN_SETTINGS_BEARER_SCHEME = HTTPBearer(auto_error=False)
ADMIN_SETTINGS_CANDIDATE_SUCCESS_MESSAGE = "管理员配置热更新候选读取成功。"
ADMIN_SETTINGS_RELOAD_SUCCESS_MESSAGE = "管理员配置热更新执行完成。"


class AdminSettingsRouteCatalog:
    """
    管理员配置热更新路由目录。
    """

    def __init__(self) -> None:
        """
        初始化管理员配置热更新路由目录。

        :returns: 无返回值。
        :rtype: None
        """

        self._accessor = DependencyContextAccessor()
        self.router = APIRouter(tags=[ADMIN_SETTINGS_ROUTE_TAG])
        self.router.add_api_route(
            ADMIN_SETTINGS_RELOAD_CANDIDATE_PATH,
            self.read_reload_candidate,
            methods=[ADMIN_SETTINGS_METHOD_GET],
            response_model=ResponseEnvelope[AdminSettingsReloadCandidateEnvelope],
            dependencies=[Depends(self.require_settings_reload)],
        )
        self.router.add_api_route(
            ADMIN_SETTINGS_RELOAD_PATH,
            self.apply_reload,
            methods=[ADMIN_SETTINGS_METHOD_POST],
            response_model=ResponseEnvelope[AdminSettingsReloadResultEnvelope],
            dependencies=[Depends(self.require_settings_reload)],
        )

    async def require_settings_reload(
        self,
        request: Request,
        _credentials: HTTPAuthorizationCredentials | None = Security(ADMIN_SETTINGS_BEARER_SCHEME),
    ) -> None:
        """
        校验管理员配置热更新权限。

        :param request: 当前 HTTP 请求对象。
        :type request: Request
        :param _credentials: OpenAPI Bearer 安全声明载荷。
        :type _credentials: HTTPAuthorizationCredentials | None
        :returns: 无返回值。
        :rtype: None
        """

        self._accessor.read_authorized_principal(
            request,
            ADMIN_SETTINGS_RELOAD_AUTHORIZATION_REQUIREMENT,
        )

    async def read_reload_candidate(
        self,
        request: Request,
    ) -> ResponseEnvelope[AdminSettingsReloadCandidateEnvelope]:
        """
        读取管理员配置热更新候选。

        :param request: 当前 HTTP 请求对象。
        :type request: Request
        :returns: 管理员配置热更新候选响应。
        :rtype: ResponseEnvelope[AdminSettingsReloadCandidateEnvelope]
        """

        candidate = await self._accessor.read_request_execution_bridge(request).run_sync(
            execution_name=ADMIN_SETTINGS_REQUEST_EXECUTION_NAME,
            callable_object=self._accessor.read_build_admin_settings_reload_candidate_usecase(
                request
            ).execute,
        )
        detail = AdminSettingsReloadCandidatePayload.from_candidate(candidate)
        return self._accessor.read_response_factory(request).build(
            code=str(SuccessCode.OK),
            message=ADMIN_SETTINGS_CANDIDATE_SUCCESS_MESSAGE,
            request_scope=self._accessor.read_request_scope(request),
            data=AdminSettingsReloadCandidateEnvelope(
                header=AdminSettingsReloadHeader(
                    kind=AdminSettingsReloadKind.CANDIDATE,
                    operation_name=AdminSettingsReloadOperationName.READ_CANDIDATE,
                ),
                detail=detail,
            ),
        )

    async def apply_reload(
        self,
        request: Request,
        _command: AdminSettingsReloadRequestEnvelope,
    ) -> ResponseEnvelope[AdminSettingsReloadResultEnvelope]:
        """
        执行管理员配置热更新。

        :param request: 当前 HTTP 请求对象。
        :type request: Request
        :param _command: 管理员配置热更新请求信封。
        :type _command: AdminSettingsReloadRequestEnvelope
        :returns: 管理员配置热更新结果响应。
        :rtype: ResponseEnvelope[AdminSettingsReloadResultEnvelope]
        """

        result = await self._accessor.read_request_execution_bridge(request).run_sync(
            execution_name=ADMIN_SETTINGS_REQUEST_EXECUTION_NAME,
            callable_object=self._accessor.read_apply_admin_settings_reload_usecase(
                request
            ).execute,
        )
        detail = AdminSettingsReloadResultPayload.from_result(result)
        return self._accessor.read_response_factory(request).build(
            code=str(SuccessCode.OK),
            message=ADMIN_SETTINGS_RELOAD_SUCCESS_MESSAGE,
            request_scope=self._accessor.read_request_scope(request),
            data=AdminSettingsReloadResultEnvelope(
                header=AdminSettingsReloadHeader(
                    kind=AdminSettingsReloadKind.RESULT,
                    operation_name=AdminSettingsReloadOperationName.RELOAD_RESULT,
                ),
                detail=detail,
            ),
        )


class AdminSettingsBundleProvider(WebBundleProvider):
    """
    管理员配置热更新模块提供者。
    """

    module_name = ApplicationModuleName.ADMIN_SETTINGS.value

    def provide(self) -> WebBundleProviderEnvelope:
        """
        提供管理员配置热更新模块信封。

        :returns: Web 模块提供者信封。
        :rtype: WebBundleProviderEnvelope
        """

        return WebBundleProviderEnvelope(
            header=WebBundleProviderHeader(module_name=self.module_name),
            detail=WebBundleProviderDetail(provider_name=self.__class__.__name__),
            bundle=WebBundle(
                module_name=self.module_name,
                router=AdminSettingsRouteCatalog().router,
            ),
        )
