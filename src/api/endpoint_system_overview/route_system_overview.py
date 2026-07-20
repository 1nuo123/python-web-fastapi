"""
路由系统概览API 接口层模块。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.api.dependency_context_accessor import DependencyContextAccessor
from src.api.endpoint_system_overview.contract_system_overview import (
    SystemOverviewAdminPayload,
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
    SYSTEM_INFO_AUTHORIZATION_REQUIREMENT,
)

SYSTEM_ROUTE_TAG = "system"
SYSTEM_INFO_PATH = "/system/info"
SYSTEM_REQUEST_EXECUTION_NAME = DEFAULT_SYNC_REQUEST_EXECUTION_NAME
SYSTEM_BEARER_SCHEME = HTTPBearer(auto_error=False)


class SystemOverviewRouteCatalog:
    """
    系统概览路由目录，负责注册接口与响应契约。
    """

    def __init__(self) -> None:
        """
        初始化系统概览路由目录。

        :returns: 无返回值。
        :rtype: None
        """

        self._accessor = DependencyContextAccessor()
        self.router = APIRouter(tags=[SYSTEM_ROUTE_TAG])
        self.router.add_api_route(
            SYSTEM_INFO_PATH,
            self.get_info,
            methods=["GET"],
            response_model=ResponseEnvelope[SystemOverviewAdminPayload],
            dependencies=[Depends(self.require_system_info)],
        )

    async def require_system_info(
        self,
        request: Request,
        _credentials: HTTPAuthorizationCredentials | None = Security(SYSTEM_BEARER_SCHEME),
    ) -> None:
        """
        校验系统概览接口的路由级授权。

        :param request: 当前 HTTP 请求对象。
        :type request: Request
        :param _credentials: OpenAPI Bearer 安全声明载荷。
        :type _credentials: HTTPAuthorizationCredentials | None
        :returns: 无返回值。
        :rtype: None
        """

        self._accessor.read_authorized_principal(
            request,
            SYSTEM_INFO_AUTHORIZATION_REQUIREMENT,
        )

    async def get_info(
        self,
        request: Request,
    ) -> ResponseEnvelope[SystemOverviewAdminPayload]:
        """
        获取系统概览信息。

        :param request: 当前 HTTP 请求对象，用于读取状态、请求头和依赖。约束：需符合 ``Request`` 注解。
        :type request: Request
        :returns: 返回读取到的对象或状态快照。
        :rtype: ResponseEnvelope[SystemOverviewAdminPayload]
        """

        # 系统概览读取仍走同步用例，路由层通过桥接器隔离事件循环阻塞风险。
        result = await self._accessor.read_request_execution_bridge(request).run_sync(
            execution_name=SYSTEM_REQUEST_EXECUTION_NAME,
            callable_object=self._accessor.read_system_overview_usecase(request).execute,
        )
        payload = SystemOverviewAdminPayload.from_result(result)
        return self._accessor.read_response_factory(request).build(
            code=str(SuccessCode.OK),
            message="系统概览读取成功。",
            request_scope=self._accessor.read_request_scope(request),
            data=payload,
        )


class SystemOverviewBundleProvider(WebBundleProvider):
    """
    系统概览模块提供者。
    """

    module_name = ApplicationModuleName.SYSTEM_OVERVIEW.value

    def provide(self) -> WebBundleProviderEnvelope:
        """
        提供系统概览模块信封。
        """

        return WebBundleProviderEnvelope(
            header=WebBundleProviderHeader(module_name=self.module_name),
            detail=WebBundleProviderDetail(provider_name=self.__class__.__name__),
            bundle=WebBundle(
                module_name=self.module_name,
                router=SystemOverviewRouteCatalog().router,
            ),
        )
