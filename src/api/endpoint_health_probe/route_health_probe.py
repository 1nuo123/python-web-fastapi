"""
路由健康探针API 接口层模块。
"""

from __future__ import annotations

from http import HTTPStatus

from fastapi import APIRouter, Request

from src.api.dependency_context_accessor import DependencyContextAccessor
from src.api.endpoint_health_probe.contract_health_probe import HealthProbePayload
from src.api.web_bundle_catalog import (
    WebBundleProvider,
    WebBundleProviderDetail,
    WebBundleProviderEnvelope,
    WebBundleProviderHeader,
)
from src.core.exception_contract.error_code_catalog_contract import CoreErrorCode, SuccessCode
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.http_contract.request_execution_contract import (
    DEFAULT_SYNC_REQUEST_EXECUTION_NAME,
)
from src.core.http_contract.response_envelope_contract import ResponseEnvelope
from src.core.http_contract.web_bundle_contract import ApplicationModuleName, WebBundle

HEALTH_ROUTE_TAG = "health"
HEALTH_LIVE_PATH = "/health/live"
HEALTH_READY_PATH = "/health/ready"
HEALTH_LIVE_PROBE_KIND = "live"
HEALTH_READY_PROBE_KIND = "ready"
HEALTH_REQUEST_EXECUTION_NAME = DEFAULT_SYNC_REQUEST_EXECUTION_NAME


class HealthProbeRouteCatalog:
    """
    健康探针路由目录，负责注册接口与响应契约。
    """

    def __init__(self) -> None:
        """
        初始化健康探针路由目录。

        :returns: 无返回值。
        :rtype: None
        """

        self._accessor = DependencyContextAccessor()
        self.router = APIRouter(tags=[HEALTH_ROUTE_TAG])
        self.router.add_api_route(
            HEALTH_LIVE_PATH,
            self.get_live,
            methods=["GET"],
            response_model=ResponseEnvelope[HealthProbePayload],
        )
        self.router.add_api_route(
            HEALTH_READY_PATH,
            self.get_ready,
            methods=["GET"],
            response_model=ResponseEnvelope[HealthProbePayload],
        )

    async def get_live(self, request: Request) -> ResponseEnvelope[HealthProbePayload]:
        """
        获取存活探针结果。

        :param request: 当前 HTTP 请求对象，用于读取状态、请求头和依赖。约束：需符合 ``Request`` 注解。
        :type request: Request
        :returns: 返回读取到的对象或状态快照。
        :rtype: ResponseEnvelope[HealthProbePayload]
        """

        # 健康探针用例当前仍是同步主干，通过桥接器卸载避免阻塞事件循环。
        result = await self._accessor.read_request_execution_bridge(request).run_sync(
            execution_name=HEALTH_REQUEST_EXECUTION_NAME,
            callable_object=self._accessor.read_health_probe_usecase(request).execute,
            probe_kind=HEALTH_LIVE_PROBE_KIND,
        )
        payload = HealthProbePayload.from_result(result)
        return self._accessor.read_response_factory(request).build(
            code=str(SuccessCode.OK),
            message="健康探针正常。",
            request_scope=self._accessor.read_request_scope(request),
            data=payload,
        )

    async def get_ready(self, request: Request) -> ResponseEnvelope[HealthProbePayload]:
        """
        获取就绪。

        :param request: 当前 HTTP 请求对象，用于读取状态、请求头和依赖。约束：需符合 ``Request`` 注解。
        :type request: Request
        :returns: 返回读取到的对象或状态快照。
        :rtype: ResponseEnvelope[HealthProbePayload]
        :raises HttpFaultException: 当业务校验失败、资源未就绪、配置错误或令牌状态异常时抛出。
        """

        # 就绪探针需要读取同步资源状态，因此同样通过桥接器执行同步用例。
        result = await self._accessor.read_request_execution_bridge(request).run_sync(
            execution_name=HEALTH_REQUEST_EXECUTION_NAME,
            callable_object=self._accessor.read_health_probe_usecase(request).execute,
            probe_kind=HEALTH_READY_PROBE_KIND,
        )
        # 当系统启用了严格就绪探针时，未就绪状态必须转换为 503。
        if not result.ready and self._accessor.read_ready_probe_enabled(request):
            raise HttpFaultException(
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                error_code=CoreErrorCode.RESOURCE_NOT_READY,
                message="应用尚未就绪。",
            )
        payload = HealthProbePayload.from_result(result)
        return self._accessor.read_response_factory(request).build(
            code=str(SuccessCode.OK),
            message="就绪探针正常。",
            request_scope=self._accessor.read_request_scope(request),
            data=payload,
        )


class HealthProbeBundleProvider(WebBundleProvider):
    """
    健康探针模块提供者。
    """

    module_name = ApplicationModuleName.HEALTH_PROBE.value

    def provide(self) -> WebBundleProviderEnvelope:
        """
        提供健康探针模块信封。
        """

        return WebBundleProviderEnvelope(
            header=WebBundleProviderHeader(module_name=self.module_name),
            detail=WebBundleProviderDetail(provider_name=self.__class__.__name__),
            bundle=WebBundle(
                module_name=self.module_name,
                router=HealthProbeRouteCatalog().router,
            ),
        )
