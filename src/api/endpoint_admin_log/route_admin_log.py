"""
管理员日志与安全事件查询路由。
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.api.dependency_context_accessor import DependencyContextAccessor
from src.api.endpoint_admin_log.contract_admin_log import (
    ADMIN_LOG_QUERY_LIMIT_DEFAULT,
    ADMIN_LOG_QUERY_LIMIT_MAXIMUM,
    ADMIN_LOG_QUERY_LIMIT_MINIMUM,
    AdminLogHeader,
    AdminLogOperationName,
    AdminLogPayloadKind,
    AdminLogRecordListEnvelope,
    AdminLogRecordListPayload,
    AdminSecurityEventListEnvelope,
    AdminSecurityEventListPayload,
)
from src.api.web_bundle_catalog import (
    WebBundleProvider,
    WebBundleProviderDetail,
    WebBundleProviderEnvelope,
    WebBundleProviderHeader,
)
from src.application.ports.admin_log_query_port import (
    AdminLogRecordFilter,
    AdminSecurityEventFilter,
)
from src.core.exception_contract.error_code_catalog_contract import SuccessCode
from src.core.http_contract.request_execution_contract import (
    DEFAULT_SYNC_REQUEST_EXECUTION_NAME,
)
from src.core.http_contract.response_envelope_contract import ResponseEnvelope
from src.core.http_contract.web_bundle_contract import ApplicationModuleName, WebBundle
from src.core.logging_contract.log_event_contract import LogEventKind, LogLevel
from src.core.security_contract.security_event_contract import (
    SecurityEventDecision,
    SecurityEventSeverity,
    SecurityEventType,
)
from src.domain.auth.admin_route_authorization_policy import (
    ADMIN_LOG_QUERY_AUTHORIZATION_REQUIREMENT,
)

ADMIN_LOG_ROUTE_TAG = "admin_log"
ADMIN_LOG_RECORDS_PATH = "/admin/logs"
ADMIN_SECURITY_EVENTS_PATH = "/admin/security-events"
ADMIN_LOG_METHOD_GET = "GET"
ADMIN_LOG_REQUEST_EXECUTION_NAME = DEFAULT_SYNC_REQUEST_EXECUTION_NAME
ADMIN_LOG_BEARER_SCHEME = HTTPBearer(auto_error=False)
ADMIN_LOG_RECORDS_SUCCESS_MESSAGE = "管理员日志查询成功。"
ADMIN_SECURITY_EVENTS_SUCCESS_MESSAGE = "管理员安全事件查询成功。"
ADMIN_LOG_LEVEL_DESCRIPTION = "日志级别过滤。"
ADMIN_LOG_EVENT_KIND_DESCRIPTION = "日志事件类型过滤。"
ADMIN_LOG_REQUEST_ID_DESCRIPTION = "请求标识过滤。"
ADMIN_LOG_TRACE_ID_DESCRIPTION = "链路标识过滤。"
ADMIN_LOG_OCCURRED_FROM_DESCRIPTION = "日志起始时间过滤。"
ADMIN_LOG_OCCURRED_TO_DESCRIPTION = "日志结束时间过滤。"
ADMIN_LOG_LIMIT_DESCRIPTION = "返回记录数量上限。"
ADMIN_SECURITY_EVENT_TYPE_DESCRIPTION = "安全事件类型过滤。"
ADMIN_SECURITY_EVENT_SEVERITY_DESCRIPTION = "安全事件严重级别过滤。"
ADMIN_SECURITY_EVENT_DECISION_DESCRIPTION = "安全事件决策过滤。"


class AdminLogRouteCatalog:
    """
    管理员日志查询路由目录。
    """

    def __init__(self) -> None:
        """
        初始化管理员日志查询路由目录。

        :returns: 无返回值。
        :rtype: None
        """

        self._accessor = DependencyContextAccessor()
        self.router = APIRouter(tags=[ADMIN_LOG_ROUTE_TAG])
        self.router.add_api_route(
            ADMIN_LOG_RECORDS_PATH,
            self.list_log_records,
            methods=[ADMIN_LOG_METHOD_GET],
            response_model=ResponseEnvelope[AdminLogRecordListEnvelope],
            dependencies=[Depends(self.require_log_query)],
        )
        self.router.add_api_route(
            ADMIN_SECURITY_EVENTS_PATH,
            self.list_security_events,
            methods=[ADMIN_LOG_METHOD_GET],
            response_model=ResponseEnvelope[AdminSecurityEventListEnvelope],
            dependencies=[Depends(self.require_log_query)],
        )

    async def require_log_query(
        self,
        request: Request,
        _credentials: HTTPAuthorizationCredentials | None = Security(ADMIN_LOG_BEARER_SCHEME),
    ) -> None:
        """
        校验管理员日志查询权限。

        :param request: 当前 HTTP 请求对象。
        :type request: Request
        :param _credentials: OpenAPI Bearer 安全声明载荷。
        :type _credentials: HTTPAuthorizationCredentials | None
        :returns: 无返回值。
        :rtype: None
        """

        self._accessor.read_authorized_principal(
            request,
            ADMIN_LOG_QUERY_AUTHORIZATION_REQUIREMENT,
        )

    async def list_log_records(
        self,
        request: Request,
        level: LogLevel | None = Query(
            default=None,
            description=ADMIN_LOG_LEVEL_DESCRIPTION,
        ),
        event_kind: LogEventKind | None = Query(
            default=None,
            description=ADMIN_LOG_EVENT_KIND_DESCRIPTION,
        ),
        request_id: str | None = Query(
            default=None,
            description=ADMIN_LOG_REQUEST_ID_DESCRIPTION,
        ),
        trace_id: str | None = Query(
            default=None,
            description=ADMIN_LOG_TRACE_ID_DESCRIPTION,
        ),
        occurred_from: datetime | None = Query(
            default=None,
            description=ADMIN_LOG_OCCURRED_FROM_DESCRIPTION,
        ),
        occurred_to: datetime | None = Query(
            default=None,
            description=ADMIN_LOG_OCCURRED_TO_DESCRIPTION,
        ),
        limit: int = Query(
            default=ADMIN_LOG_QUERY_LIMIT_DEFAULT,
            ge=ADMIN_LOG_QUERY_LIMIT_MINIMUM,
            le=ADMIN_LOG_QUERY_LIMIT_MAXIMUM,
            description=ADMIN_LOG_LIMIT_DESCRIPTION,
        ),
    ) -> ResponseEnvelope[AdminLogRecordListEnvelope]:
        """
        查询管理员日志记录。

        :param request: 当前 HTTP 请求对象。
        :type request: Request
        :param level: 日志级别过滤。
        :type level: LogLevel | None
        :param event_kind: 日志事件类型过滤。
        :type event_kind: LogEventKind | None
        :param request_id: 请求标识过滤。
        :type request_id: str | None
        :param trace_id: 链路标识过滤。
        :type trace_id: str | None
        :param occurred_from: 日志起始时间过滤。
        :type occurred_from: datetime | None
        :param occurred_to: 日志结束时间过滤。
        :type occurred_to: datetime | None
        :param limit: 返回记录数量上限。
        :type limit: int
        :returns: 管理员日志记录列表响应。
        :rtype: ResponseEnvelope[AdminLogRecordListEnvelope]
        """

        snapshots = await self._accessor.read_request_execution_bridge(request).run_sync(
            execution_name=ADMIN_LOG_REQUEST_EXECUTION_NAME,
            callable_object=self._accessor.read_list_admin_log_records_usecase(request).execute,
            query_filter=AdminLogRecordFilter(
                level=level,
                event_kind=event_kind,
                request_id=request_id,
                trace_id=trace_id,
                occurred_from=occurred_from,
                occurred_to=occurred_to,
                limit=limit,
            ),
        )
        detail = AdminLogRecordListPayload.from_snapshots(snapshots)
        return self._accessor.read_response_factory(request).build(
            code=str(SuccessCode.OK),
            message=ADMIN_LOG_RECORDS_SUCCESS_MESSAGE,
            request_scope=self._accessor.read_request_scope(request),
            data=AdminLogRecordListEnvelope(
                header=AdminLogHeader(
                    kind=AdminLogPayloadKind.LOG_RECORD_LIST,
                    operation_name=AdminLogOperationName.LOG_RECORD_LIST,
                ),
                detail=detail,
            ),
        )

    async def list_security_events(
        self,
        request: Request,
        event_type: SecurityEventType | None = Query(
            default=None,
            description=ADMIN_SECURITY_EVENT_TYPE_DESCRIPTION,
        ),
        severity: SecurityEventSeverity | None = Query(
            default=None,
            description=ADMIN_SECURITY_EVENT_SEVERITY_DESCRIPTION,
        ),
        decision: SecurityEventDecision | None = Query(
            default=None,
            description=ADMIN_SECURITY_EVENT_DECISION_DESCRIPTION,
        ),
        occurred_from: datetime | None = Query(
            default=None,
            description=ADMIN_LOG_OCCURRED_FROM_DESCRIPTION,
        ),
        occurred_to: datetime | None = Query(
            default=None,
            description=ADMIN_LOG_OCCURRED_TO_DESCRIPTION,
        ),
        limit: int = Query(
            default=ADMIN_LOG_QUERY_LIMIT_DEFAULT,
            ge=ADMIN_LOG_QUERY_LIMIT_MINIMUM,
            le=ADMIN_LOG_QUERY_LIMIT_MAXIMUM,
            description=ADMIN_LOG_LIMIT_DESCRIPTION,
        ),
    ) -> ResponseEnvelope[AdminSecurityEventListEnvelope]:
        """
        查询管理员安全事件。

        :param request: 当前 HTTP 请求对象。
        :type request: Request
        :param event_type: 安全事件类型过滤。
        :type event_type: SecurityEventType | None
        :param severity: 安全事件严重级别过滤。
        :type severity: SecurityEventSeverity | None
        :param decision: 安全事件决策过滤。
        :type decision: SecurityEventDecision | None
        :param occurred_from: 日志起始时间过滤。
        :type occurred_from: datetime | None
        :param occurred_to: 日志结束时间过滤。
        :type occurred_to: datetime | None
        :param limit: 返回记录数量上限。
        :type limit: int
        :returns: 管理员安全事件列表响应。
        :rtype: ResponseEnvelope[AdminSecurityEventListEnvelope]
        """

        snapshots = await self._accessor.read_request_execution_bridge(request).run_sync(
            execution_name=ADMIN_LOG_REQUEST_EXECUTION_NAME,
            callable_object=self._accessor.read_list_admin_security_events_usecase(request).execute,
            query_filter=AdminSecurityEventFilter(
                event_type=event_type,
                severity=severity,
                decision=decision,
                occurred_from=occurred_from,
                occurred_to=occurred_to,
                limit=limit,
            ),
        )
        detail = AdminSecurityEventListPayload.from_snapshots(snapshots)
        return self._accessor.read_response_factory(request).build(
            code=str(SuccessCode.OK),
            message=ADMIN_SECURITY_EVENTS_SUCCESS_MESSAGE,
            request_scope=self._accessor.read_request_scope(request),
            data=AdminSecurityEventListEnvelope(
                header=AdminLogHeader(
                    kind=AdminLogPayloadKind.SECURITY_EVENT_LIST,
                    operation_name=AdminLogOperationName.SECURITY_EVENT_LIST,
                ),
                detail=detail,
            ),
        )


class AdminLogBundleProvider(WebBundleProvider):
    """
    管理员日志查询模块提供者。
    """

    module_name = ApplicationModuleName.ADMIN_LOG.value

    def provide(self) -> WebBundleProviderEnvelope:
        """
        提供管理员日志查询模块信封。

        :returns: Web 模块提供者信封。
        :rtype: WebBundleProviderEnvelope
        """

        return WebBundleProviderEnvelope(
            header=WebBundleProviderHeader(module_name=self.module_name),
            detail=WebBundleProviderDetail(provider_name=self.__class__.__name__),
            bundle=WebBundle(
                module_name=self.module_name,
                router=AdminLogRouteCatalog().router,
            ),
        )
