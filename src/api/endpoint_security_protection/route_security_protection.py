"""
安全防护管理路由模块。
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.api.dependency_context_accessor import DependencyContextAccessor
from src.api.endpoint_security_protection.contract_security_protection import (
    IP_BLOCK_QUERY_LIMIT_MAXIMUM,
    IP_BLOCK_QUERY_LIMIT_MINIMUM,
    SecurityIpBlockCreatePayload,
    SecurityIpBlockCreateRequest,
    SecurityIpBlockListPayload,
    SecurityIpBlockRecordPayload,
    SecurityIpBlockReleasePayload,
    SecurityIpBlockReleaseRequest,
)
from src.api.web_bundle_catalog import (
    WebBundleProvider,
    WebBundleProviderDetail,
    WebBundleProviderEnvelope,
    WebBundleProviderHeader,
)
from src.application.admin.security_protection.manage_admin_security_ip_blocks_usecase import (
    SecurityIpBlockCreateCommand,
    SecurityIpBlockEventContext,
    SecurityIpBlockGetQuery,
    SecurityIpBlockListQuery,
    SecurityIpBlockRecordSnapshot,
    SecurityIpBlockReleaseCommand,
)
from src.core.exception_contract.error_code_catalog_contract import (
    SuccessCode,
)
from src.core.http_contract.request_execution_contract import (
    DEFAULT_SYNC_REQUEST_EXECUTION_NAME,
)
from src.core.http_contract.response_envelope_contract import ResponseEnvelope
from src.core.http_contract.web_bundle_contract import ApplicationModuleName, WebBundle
from src.domain.auth.admin_route_authorization_policy import (
    SECURITY_PROTECTION_AUTHORIZATION_REQUIREMENT,
)

SECURITY_PROTECTION_ROUTE_TAG = "security_protection"
SECURITY_PROTECTION_IP_BLOCK_PATH = "/security/ip-blocks"
SECURITY_PROTECTION_IP_BLOCK_RECORD_PATH = "/security/ip-blocks/{record_id}"
SECURITY_PROTECTION_IP_BLOCK_RELEASE_PATH = "/security/ip-blocks/release"
SECURITY_PROTECTION_QUERY_LIMIT = 100
SECURITY_PROTECTION_BEARER_SCHEME = HTTPBearer(auto_error=False)
SECURITY_PROTECTION_LIST_SUCCESS_MESSAGE = "IP 封禁记录查询成功。"
SECURITY_PROTECTION_CREATE_SUCCESS_MESSAGE = "IP 封禁创建成功。"
SECURITY_PROTECTION_GET_SUCCESS_MESSAGE = "IP 封禁记录读取成功。"
SECURITY_PROTECTION_RELEASE_SUCCESS_MESSAGE = "IP 封禁释放成功。"
SECURITY_PROTECTION_REQUEST_EXECUTION_NAME = DEFAULT_SYNC_REQUEST_EXECUTION_NAME
SECURITY_PROTECTION_RECORD_ID_DESCRIPTION = "封禁记录 ID。"
SECURITY_PROTECTION_LIMIT_DESCRIPTION = "返回记录数量上限。"
SECURITY_PROTECTION_STATUS_DESCRIPTION = "封禁状态过滤。"
SECURITY_PROTECTION_IP_DIGEST_DESCRIPTION = "IP 摘要过滤。"


class SecurityProtectionRouteCatalog:
    """
    安全防护管理路由目录。
    """

    def __init__(self) -> None:
        """
        初始化安全防护管理路由目录。
        """

        self._accessor = DependencyContextAccessor()
        self.router = APIRouter(tags=[SECURITY_PROTECTION_ROUTE_TAG])
        self.router.add_api_route(
            SECURITY_PROTECTION_IP_BLOCK_PATH,
            self.list_ip_blocks,
            methods=["GET"],
            response_model=ResponseEnvelope[SecurityIpBlockListPayload],
            dependencies=[Depends(self.require_security_admin)],
        )
        self.router.add_api_route(
            SECURITY_PROTECTION_IP_BLOCK_PATH,
            self.create_ip_block,
            methods=["POST"],
            response_model=ResponseEnvelope[SecurityIpBlockCreatePayload],
            dependencies=[Depends(self.require_security_admin)],
        )
        self.router.add_api_route(
            SECURITY_PROTECTION_IP_BLOCK_RELEASE_PATH,
            self.release_ip_block,
            methods=["POST"],
            response_model=ResponseEnvelope[SecurityIpBlockReleasePayload],
            dependencies=[Depends(self.require_security_admin)],
        )
        self.router.add_api_route(
            SECURITY_PROTECTION_IP_BLOCK_RECORD_PATH,
            self.get_ip_block,
            methods=["GET"],
            response_model=ResponseEnvelope[SecurityIpBlockRecordPayload],
            dependencies=[Depends(self.require_security_admin)],
        )

    async def require_security_admin(
        self,
        request: Request,
        _credentials: HTTPAuthorizationCredentials | None = Security(
            SECURITY_PROTECTION_BEARER_SCHEME
        ),
    ) -> None:
        """
        校验安全防护管理权限。
        """

        self._accessor.read_authorized_principal(
            request,
            SECURITY_PROTECTION_AUTHORIZATION_REQUIREMENT,
        )

    async def list_ip_blocks(
        self,
        request: Request,
        limit: int = Query(
            default=SECURITY_PROTECTION_QUERY_LIMIT,
            ge=IP_BLOCK_QUERY_LIMIT_MINIMUM,
            le=IP_BLOCK_QUERY_LIMIT_MAXIMUM,
            description=SECURITY_PROTECTION_LIMIT_DESCRIPTION,
        ),
        status: str | None = Query(
            default=None,
            description=SECURITY_PROTECTION_STATUS_DESCRIPTION,
        ),
        ip_digest: str | None = Query(
            default=None,
            description=SECURITY_PROTECTION_IP_DIGEST_DESCRIPTION,
        ),
    ) -> ResponseEnvelope[SecurityIpBlockListPayload]:
        """
        查询 IP 封禁记录。
        """

        records = await self._accessor.read_request_execution_bridge(request).run_sync(
            execution_name=SECURITY_PROTECTION_REQUEST_EXECUTION_NAME,
            callable_object=self._accessor.read_list_admin_security_ip_blocks_usecase(
                request
            ).execute,
            query=SecurityIpBlockListQuery(
                limit=limit,
                status=status,
                ip_digest=ip_digest,
            ),
        )
        payload = SecurityIpBlockListPayload(
            records=[self._build_record_payload(record) for record in records]
        )
        return self._accessor.read_response_factory(request).build(
            code=str(SuccessCode.OK),
            message=SECURITY_PROTECTION_LIST_SUCCESS_MESSAGE,
            request_scope=self._accessor.read_request_scope(request),
            data=payload,
        )

    async def create_ip_block(
        self,
        request: Request,
        command: SecurityIpBlockCreateRequest,
    ) -> ResponseEnvelope[SecurityIpBlockCreatePayload]:
        """
        手动创建 IP 封禁记录。
        """

        record = await self._accessor.read_request_execution_bridge(request).run_sync(
            execution_name=SECURITY_PROTECTION_REQUEST_EXECUTION_NAME,
            callable_object=self._accessor.read_create_admin_security_ip_block_usecase(
                request
            ).execute,
            command=SecurityIpBlockCreateCommand(
                ip_digest=command.ip_digest,
                reason=command.reason,
                block_seconds=command.block_seconds,
                event_context=self._build_event_context(request),
            ),
        )
        payload = SecurityIpBlockCreatePayload(
            record=self._build_record_payload(record),
        )
        return self._accessor.read_response_factory(request).build(
            code=str(SuccessCode.OK),
            message=SECURITY_PROTECTION_CREATE_SUCCESS_MESSAGE,
            request_scope=self._accessor.read_request_scope(request),
            data=payload,
        )

    async def get_ip_block(
        self,
        request: Request,
        record_id: UUID = Path(description=SECURITY_PROTECTION_RECORD_ID_DESCRIPTION),
    ) -> ResponseEnvelope[SecurityIpBlockRecordPayload]:
        """
        按记录 ID 查询 IP 封禁记录。
        """

        record = await self._accessor.read_request_execution_bridge(request).run_sync(
            execution_name=SECURITY_PROTECTION_REQUEST_EXECUTION_NAME,
            callable_object=self._accessor.read_get_admin_security_ip_block_usecase(
                request
            ).execute,
            query=SecurityIpBlockGetQuery(record_id=record_id),
        )
        payload = self._build_record_payload(record)
        return self._accessor.read_response_factory(request).build(
            code=str(SuccessCode.OK),
            message=SECURITY_PROTECTION_GET_SUCCESS_MESSAGE,
            request_scope=self._accessor.read_request_scope(request),
            data=payload,
        )

    async def release_ip_block(
        self,
        request: Request,
        command: SecurityIpBlockReleaseRequest,
    ) -> ResponseEnvelope[SecurityIpBlockReleasePayload]:
        """
        释放 IP 封禁记录。
        """

        result = await self._accessor.read_request_execution_bridge(request).run_sync(
            execution_name=SECURITY_PROTECTION_REQUEST_EXECUTION_NAME,
            callable_object=self._accessor.read_release_admin_security_ip_block_usecase(
                request
            ).execute,
            command=SecurityIpBlockReleaseCommand(
                ip_digest=command.ip_digest,
                released_reason=command.released_reason,
                event_context=self._build_event_context(request),
            ),
        )
        payload = SecurityIpBlockReleasePayload(
            ip_digest=result.ip_digest,
            released=result.released,
        )
        return self._accessor.read_response_factory(request).build(
            code=str(SuccessCode.OK),
            message=SECURITY_PROTECTION_RELEASE_SUCCESS_MESSAGE,
            request_scope=self._accessor.read_request_scope(request),
            data=payload,
        )

    def _build_record_payload(
        self,
        record: SecurityIpBlockRecordSnapshot,
    ) -> SecurityIpBlockRecordPayload:
        """
        构建 IP 封禁记录响应载荷。
        """

        return SecurityIpBlockRecordPayload(
            record_id=str(record.record_id),
            ip_digest=record.ip_digest,
            reason=record.reason,
            status=record.status,
            blocked_until_epoch=record.blocked_until_epoch,
            released_reason=record.released_reason,
        )

    def _build_event_context(self, request: Request) -> SecurityIpBlockEventContext:
        """
        构建安全 IP 封禁事件上下文。
        """

        return SecurityIpBlockEventContext(
            request_scope=self._accessor.read_request_scope(request),
        )


class SecurityProtectionBundleProvider(WebBundleProvider):
    """
    安全防护管理模块提供者。
    """

    module_name = ApplicationModuleName.SECURITY_PROTECTION.value

    def provide(self) -> WebBundleProviderEnvelope:
        """
        提供安全防护管理模块信封。
        """

        return WebBundleProviderEnvelope(
            header=WebBundleProviderHeader(module_name=self.module_name),
            detail=WebBundleProviderDetail(provider_name=self.__class__.__name__),
            bundle=WebBundle(
                module_name=self.module_name,
                router=SecurityProtectionRouteCatalog().router,
            ),
        )
