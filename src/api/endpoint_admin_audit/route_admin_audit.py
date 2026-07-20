"""
业务后台审计路由。
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.api.dependency_context_accessor import DependencyContextAccessor
from src.api.endpoint_admin_audit.contract_admin_audit import (
    ADMIN_AUDIT_OFFSET_MINIMUM,
    ADMIN_AUDIT_PAGE_SIZE_DEFAULT,
    ADMIN_AUDIT_PAGE_SIZE_MAXIMUM,
    ADMIN_AUDIT_PAGE_SIZE_MINIMUM,
    ADMIN_AUDIT_SCHEMA_VERSION,
    AdminAuditEnvelope,
    AdminAuditEventListPayload,
    AdminAuditHeader,
    AdminAuditOperationName,
    AdminAuditPayloadKind,
    AdminAuditQueryPayload,
)
from src.api.web_bundle_catalog import (
    WebBundleProvider,
    WebBundleProviderDetail,
    WebBundleProviderEnvelope,
    WebBundleProviderHeader,
)
from src.application.ports.admin_audit_query_port import AdminAuditAction
from src.core.exception_contract.error_code_catalog_contract import SuccessCode
from src.core.http_contract.request_execution_contract import (
    DEFAULT_SYNC_REQUEST_EXECUTION_NAME,
)
from src.core.http_contract.response_envelope_contract import ResponseEnvelope
from src.core.http_contract.web_bundle_contract import ApplicationModuleName, WebBundle
from src.domain.auth.admin_route_authorization_policy import (
    ADMIN_AUDIT_READ_AUTHORIZATION_REQUIREMENT,
)

ADMIN_AUDIT_ROUTE_TAG = "admin_audit"
ADMIN_AUDIT_EVENTS_PATH = "/admin/audit-events"
ADMIN_AUDIT_METHOD_GET = "GET"
ADMIN_AUDIT_BEARER_SCHEME = HTTPBearer(auto_error=False)
ADMIN_AUDIT_REQUEST_EXECUTION_NAME = DEFAULT_SYNC_REQUEST_EXECUTION_NAME
ADMIN_AUDIT_LIST_SUCCESS_MESSAGE = "业务审计事件列表查询成功。"
ADMIN_AUDIT_ACTOR_DESCRIPTION = "操作者主体标识。"
ADMIN_AUDIT_ACTION_DESCRIPTION = "业务审计动作。"
ADMIN_AUDIT_TARGET_KIND_DESCRIPTION = "目标对象类型。"
ADMIN_AUDIT_TARGET_ID_DESCRIPTION = "目标对象标识。"
ADMIN_AUDIT_OCCURRED_FROM_DESCRIPTION = "发生时间起点。"
ADMIN_AUDIT_OCCURRED_TO_DESCRIPTION = "发生时间终点。"
ADMIN_AUDIT_PAGE_SIZE_DESCRIPTION = "分页大小。"
ADMIN_AUDIT_OFFSET_DESCRIPTION = "分页偏移。"


class AdminAuditRouteCatalog:
    """
    业务后台审计路由目录。
    """

    def __init__(self) -> None:
        """
        初始化业务后台审计路由目录。

        :returns: 无返回值。
        :rtype: None
        """

        self._accessor = DependencyContextAccessor()
        self.router = APIRouter(tags=[ADMIN_AUDIT_ROUTE_TAG])
        self._bind_audit_routes()

    async def require_audit_read(
        self,
        request: Request,
        _credentials: HTTPAuthorizationCredentials | None = Security(ADMIN_AUDIT_BEARER_SCHEME),
    ) -> None:
        """
        校验业务审计读取权限。
        """

        self._accessor.read_authorized_principal(
            request,
            ADMIN_AUDIT_READ_AUTHORIZATION_REQUIREMENT,
        )

    async def list_audit_events(
        self,
        request: Request,
        actor_subject_id: str | None = Query(
            default=None,
            description=ADMIN_AUDIT_ACTOR_DESCRIPTION,
        ),
        action: AdminAuditAction | None = Query(
            default=None,
            description=ADMIN_AUDIT_ACTION_DESCRIPTION,
        ),
        target_kind: str | None = Query(
            default=None,
            description=ADMIN_AUDIT_TARGET_KIND_DESCRIPTION,
        ),
        target_id: str | None = Query(
            default=None,
            description=ADMIN_AUDIT_TARGET_ID_DESCRIPTION,
        ),
        occurred_from: datetime | None = Query(
            default=None,
            description=ADMIN_AUDIT_OCCURRED_FROM_DESCRIPTION,
        ),
        occurred_to: datetime | None = Query(
            default=None,
            description=ADMIN_AUDIT_OCCURRED_TO_DESCRIPTION,
        ),
        page_size: int = Query(
            default=ADMIN_AUDIT_PAGE_SIZE_DEFAULT,
            ge=ADMIN_AUDIT_PAGE_SIZE_MINIMUM,
            le=ADMIN_AUDIT_PAGE_SIZE_MAXIMUM,
            description=ADMIN_AUDIT_PAGE_SIZE_DESCRIPTION,
        ),
        offset: int = Query(
            default=ADMIN_AUDIT_OFFSET_MINIMUM,
            ge=ADMIN_AUDIT_OFFSET_MINIMUM,
            description=ADMIN_AUDIT_OFFSET_DESCRIPTION,
        ),
    ) -> ResponseEnvelope[AdminAuditEnvelope]:
        """
        查询业务审计事件列表。
        """

        query_payload = AdminAuditQueryPayload(
            actor_subject_id=actor_subject_id,
            action=action,
            target_kind=target_kind,
            target_id=target_id,
            occurred_from=occurred_from,
            occurred_to=occurred_to,
            page_size=page_size,
            offset=offset,
        )
        page = await self._accessor.read_request_execution_bridge(request).run_sync(
            execution_name=ADMIN_AUDIT_REQUEST_EXECUTION_NAME,
            callable_object=self._accessor.read_list_admin_audit_events_usecase(request).execute,
            query=query_payload.to_query(),
        )
        return self._accessor.read_response_factory(request).build(
            code=str(SuccessCode.OK),
            message=ADMIN_AUDIT_LIST_SUCCESS_MESSAGE,
            request_scope=self._accessor.read_request_scope(request),
            data=AdminAuditEnvelope(
                header=AdminAuditHeader(
                    kind=AdminAuditPayloadKind.EVENT_LIST,
                    schema_version=ADMIN_AUDIT_SCHEMA_VERSION,
                    operation_name=AdminAuditOperationName.EVENT_LIST,
                ),
                detail=AdminAuditEventListPayload.from_page(page),
            ),
        )

    def _bind_audit_routes(self) -> None:
        """
        绑定业务审计路由。
        """

        self.router.add_api_route(
            ADMIN_AUDIT_EVENTS_PATH,
            self.list_audit_events,
            methods=[ADMIN_AUDIT_METHOD_GET],
            response_model=ResponseEnvelope[AdminAuditEnvelope],
            dependencies=[Depends(self.require_audit_read)],
        )


class AdminAuditBundleProvider(WebBundleProvider):
    """
    业务后台审计模块提供者。
    """

    module_name = ApplicationModuleName.ADMIN_AUDIT.value

    def provide(self) -> WebBundleProviderEnvelope:
        """
        提供业务后台审计模块信封。
        """

        return WebBundleProviderEnvelope(
            header=WebBundleProviderHeader(module_name=self.module_name),
            detail=WebBundleProviderDetail(provider_name=self.__class__.__name__),
            bundle=WebBundle(
                module_name=self.module_name,
                router=AdminAuditRouteCatalog().router,
            ),
        )
