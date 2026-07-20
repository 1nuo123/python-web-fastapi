"""
共享 HTTP 资源管理器基础设施模块。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from http import HTTPStatus

from src.core.exception_contract.error_code_catalog_contract import CoreErrorCode
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.http_contract.outbound_http_client_contract import (
    AsyncHttpClientDetail,
    OutboundHttpClientMode,
    SyncHttpClientDetail,
)
from src.core.http_contract.runtime_resource_contract import (
    RuntimeResourceState,
    RuntimeResourceStatus,
)
from src.infrastructure.request_execution_bridge import RequestExecutionBridge
from src.infrastructure.resource_slot.shared_async_http_client import SharedAsyncHttpClient
from src.infrastructure.resource_slot.shared_http_client import SharedHttpClient
from src.infrastructure.settings.application_settings import ApplicationSettings

RESOURCE_ASYNC_HTTP_CLIENT = "shared_async_http_client"
RESOURCE_HTTP_CLIENT = "shared_http_client"


@dataclass(slots=True)
class SharedHttpResourceSet:
    """
    共享 HTTP 资源集合。
    """

    http_client: SharedHttpClient
    async_http_client: SharedAsyncHttpClient | None
    request_execution_bridge: RequestExecutionBridge
    http_state: RuntimeResourceState
    async_http_state: RuntimeResourceState


class SharedHttpResourceManager:
    """
    共享 HTTP 资源管理器。
    """

    def __init__(self, *, logger: logging.Logger) -> None:
        """
        初始化共享 HTTP 资源管理器。

        :param logger: 当前资源管理器使用的日志记录器。
        :type logger: logging.Logger
        :returns: 无返回值。
        :rtype: None
        """

        self._logger = logger

    def build_resource_set(self, settings: ApplicationSettings) -> SharedHttpResourceSet:
        """
        构建共享 HTTP 资源集合。

        :param settings: 已通过校验的应用配置快照。
        :type settings: ApplicationSettings
        :returns: 返回共享 HTTP 资源集合。
        :rtype: SharedHttpResourceSet
        """

        outbound_http_client = settings.runtime.web.outbound_http_client
        sync_http_detail = (
            outbound_http_client.detail
            if isinstance(outbound_http_client.detail, SyncHttpClientDetail)
            else None
        )
        http_client = SharedHttpClient(sync_http_detail)
        async_http_client: SharedAsyncHttpClient | None = None
        if outbound_http_client.header.mode == OutboundHttpClientMode.ASYNC_HTTP:
            async_http_detail = outbound_http_client.detail
            if not isinstance(async_http_detail, AsyncHttpClientDetail):
                raise HttpFaultException(
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                    error_code=CoreErrorCode.CONFIG_INVALID,
                    message="异步 HTTP 客户端配置无效。",
                )
            async_http_client = SharedAsyncHttpClient(async_http_detail)
        request_execution_bridge = RequestExecutionBridge(
            envelope=settings.runtime.web.request_execution,
            logger=self._logger,
        )
        return SharedHttpResourceSet(
            http_client=http_client,
            async_http_client=async_http_client,
            request_execution_bridge=request_execution_bridge,
            http_state=RuntimeResourceState(
                resource_name=RESOURCE_HTTP_CLIENT,
                status=RuntimeResourceStatus.READY,
            ),
            async_http_state=RuntimeResourceState(
                resource_name=RESOURCE_ASYNC_HTTP_CLIENT,
                status=(
                    RuntimeResourceStatus.READY
                    if async_http_client is not None
                    else RuntimeResourceStatus.STOPPED
                ),
            ),
        )

    def close_resource_set(self, resource_set: SharedHttpResourceSet) -> None:
        """
        释放共享 HTTP 资源集合。

        :param resource_set: 需要释放的共享 HTTP 资源集合。
        :type resource_set: SharedHttpResourceSet
        :returns: 无返回值。
        :rtype: None
        """

        resource_set.request_execution_bridge.close()
        if resource_set.async_http_client is not None:
            resource_set.async_http_client.close_sync()
        resource_set.http_client.close()
