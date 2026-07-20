"""管理员 scope 路由。"""

from __future__ import annotations

from fastapi import Depends, Path, Query, Request

from src.api.endpoint_admin_identity.contract_admin_identity_common import (
    ADMIN_SCOPE_DELETE_RESULT_KIND,
    AdminIdentityDeleteResultPayload,
    AdminIdentityOperationName,
    AdminIdentityPayloadKind,
)
from src.api.endpoint_admin_identity.contract_admin_identity_envelope import (
    AdminIdentityEnvelope,
)
from src.api.endpoint_admin_identity.contract_admin_scope import (
    AdminScopeCreateRequest,
    AdminScopeListPayload,
    AdminScopePayload,
    AdminScopeUpdateRequest,
)
from src.api.endpoint_admin_identity.route_admin_identity_common import (
    ADMIN_IDENTITY_ENABLED_DESCRIPTION,
    ADMIN_IDENTITY_KEYWORD_DESCRIPTION,
    ADMIN_IDENTITY_LIMIT_DESCRIPTION,
    ADMIN_IDENTITY_METHOD_DELETE,
    ADMIN_IDENTITY_METHOD_GET,
    ADMIN_IDENTITY_METHOD_PATCH,
    ADMIN_IDENTITY_METHOD_POST,
    ADMIN_IDENTITY_REQUEST_EXECUTION_NAME,
    ADMIN_IDENTITY_SCOPE_CODE_DESCRIPTION,
    ADMIN_IDENTITY_TARGET_SCOPE,
    ADMIN_SCOPE_CREATE_SUCCESS_MESSAGE,
    ADMIN_SCOPE_DELETE_SUCCESS_MESSAGE,
    ADMIN_SCOPE_DETAIL_PATH,
    ADMIN_SCOPE_DETAIL_SUCCESS_MESSAGE,
    ADMIN_SCOPE_LIST_SUCCESS_MESSAGE,
    ADMIN_SCOPE_UPDATE_SUCCESS_MESSAGE,
    ADMIN_SCOPES_PATH,
    AdminIdentityRouteSupport,
)
from src.application.admin.identity.shared.admin_identity_command import (
    AdminScopeCreateCommand,
    AdminScopeDeleteCommand,
    AdminScopeUpdateCommand,
)
from src.application.ports.admin_identity_port import (
    ADMIN_IDENTITY_QUERY_LIMIT_DEFAULT,
    ADMIN_IDENTITY_QUERY_LIMIT_MAXIMUM,
    ADMIN_IDENTITY_QUERY_LIMIT_MINIMUM,
    AdminScopeListQuery,
)
from src.core.auth_contract.authenticated_principal_contract import (
    AuthenticatedPrincipal,
)
from src.core.http_contract.response_envelope_contract import ResponseEnvelope
from src.domain.auth.admin_route_authorization_policy import (
    ADMIN_IDENTITY_SCOPE_MANAGE_AUTHORIZATION_REQUIREMENT,
)


class AdminScopeRouteCatalog(AdminIdentityRouteSupport):
    """管理员 scope 路由目录。"""

    async def list_scopes(
        self,
        request: Request,
        keyword: str | None = Query(
            default=None,
            description=ADMIN_IDENTITY_KEYWORD_DESCRIPTION,
        ),
        enabled: bool | None = Query(
            default=None,
            description=ADMIN_IDENTITY_ENABLED_DESCRIPTION,
        ),
        limit: int = Query(
            default=ADMIN_IDENTITY_QUERY_LIMIT_DEFAULT,
            ge=ADMIN_IDENTITY_QUERY_LIMIT_MINIMUM,
            le=ADMIN_IDENTITY_QUERY_LIMIT_MAXIMUM,
            description=ADMIN_IDENTITY_LIMIT_DESCRIPTION,
        ),
    ) -> ResponseEnvelope[AdminIdentityEnvelope]:
        """
        查询管理员 scope 列表。
        """

        snapshots = await self._accessor.read_request_execution_bridge(request).run_sync(
            execution_name=ADMIN_IDENTITY_REQUEST_EXECUTION_NAME,
            callable_object=self._accessor.read_list_admin_scopes_usecase(request).execute,
            query=AdminScopeListQuery(
                keyword=keyword,
                enabled=enabled,
                limit=limit,
            ),
        )
        detail = AdminScopeListPayload.from_snapshots(snapshots)
        return self._build_response(
            request=request,
            message=ADMIN_SCOPE_LIST_SUCCESS_MESSAGE,
            kind=AdminIdentityPayloadKind.SCOPE_LIST,
            operation_name=AdminIdentityOperationName.SCOPE_LIST,
            detail=detail,
        )

    async def get_scope(
        self,
        request: Request,
        scope_code: str = Path(description=ADMIN_IDENTITY_SCOPE_CODE_DESCRIPTION),
    ) -> ResponseEnvelope[AdminIdentityEnvelope]:
        """
        读取管理员 scope 详情。
        """

        snapshot = await self._accessor.read_request_execution_bridge(request).run_sync(
            execution_name=ADMIN_IDENTITY_REQUEST_EXECUTION_NAME,
            callable_object=self._accessor.read_get_admin_scope_usecase(request).execute,
            scope_code=scope_code,
        )
        return self._build_response(
            request=request,
            message=ADMIN_SCOPE_DETAIL_SUCCESS_MESSAGE,
            kind=AdminIdentityPayloadKind.SCOPE,
            operation_name=AdminIdentityOperationName.SCOPE_DETAIL,
            detail=AdminScopePayload.from_snapshot(snapshot),
        )

    async def create_scope(
        self,
        request: Request,
        command: AdminIdentityEnvelope,
    ) -> ResponseEnvelope[AdminIdentityEnvelope]:
        """
        创建管理员 scope。
        """

        principal = self._read_scope_manage_principal(request)
        detail = self._read_detail(command, AdminScopeCreateRequest)
        snapshot = await self._accessor.read_request_execution_bridge(request).run_sync(
            execution_name=ADMIN_IDENTITY_REQUEST_EXECUTION_NAME,
            callable_object=self._accessor.read_create_admin_scope_usecase(request).execute,
            command=AdminScopeCreateCommand(
                scope_code=detail.scope_code,
                scope_name=detail.scope_name,
                description=detail.description,
                enabled=detail.enabled,
            ),
        )
        self._record_identity_change(
            request=request,
            principal=principal,
            operation_name=AdminIdentityOperationName.SCOPE_CREATE,
            target_kind=ADMIN_IDENTITY_TARGET_SCOPE,
            target_id=detail.scope_code,
        )
        return self._build_response(
            request=request,
            message=ADMIN_SCOPE_CREATE_SUCCESS_MESSAGE,
            kind=AdminIdentityPayloadKind.SCOPE,
            operation_name=AdminIdentityOperationName.SCOPE_CREATE,
            detail=AdminScopePayload.from_snapshot(snapshot),
        )

    async def update_scope(
        self,
        request: Request,
        command: AdminIdentityEnvelope,
        scope_code: str = Path(description=ADMIN_IDENTITY_SCOPE_CODE_DESCRIPTION),
    ) -> ResponseEnvelope[AdminIdentityEnvelope]:
        """
        更新管理员 scope。
        """

        principal = self._read_scope_manage_principal(request)
        detail = self._read_detail(command, AdminScopeUpdateRequest)
        snapshot = await self._accessor.read_request_execution_bridge(request).run_sync(
            execution_name=ADMIN_IDENTITY_REQUEST_EXECUTION_NAME,
            callable_object=self._accessor.read_update_admin_scope_usecase(request).execute,
            command=AdminScopeUpdateCommand(
                actor_subject_id=principal.subject_id,
                scope_code=scope_code,
                scope_name=detail.scope_name,
                description=detail.description,
                enabled=detail.enabled,
            ),
        )
        self._record_identity_change(
            request=request,
            principal=principal,
            operation_name=AdminIdentityOperationName.SCOPE_UPDATE,
            target_kind=ADMIN_IDENTITY_TARGET_SCOPE,
            target_id=scope_code,
        )
        return self._build_response(
            request=request,
            message=ADMIN_SCOPE_UPDATE_SUCCESS_MESSAGE,
            kind=AdminIdentityPayloadKind.SCOPE,
            operation_name=AdminIdentityOperationName.SCOPE_UPDATE,
            detail=AdminScopePayload.from_snapshot(snapshot),
        )

    async def delete_scope(
        self,
        request: Request,
        scope_code: str = Path(description=ADMIN_IDENTITY_SCOPE_CODE_DESCRIPTION),
    ) -> ResponseEnvelope[AdminIdentityEnvelope]:
        """
        删除管理员 scope。
        """

        principal = self._read_scope_manage_principal(request)
        result = await self._accessor.read_request_execution_bridge(request).run_sync(
            execution_name=ADMIN_IDENTITY_REQUEST_EXECUTION_NAME,
            callable_object=self._accessor.read_delete_admin_scope_usecase(request).execute,
            command=AdminScopeDeleteCommand(scope_code=scope_code),
        )
        self._record_identity_change(
            request=request,
            principal=principal,
            operation_name=AdminIdentityOperationName.SCOPE_DELETE,
            target_kind=ADMIN_IDENTITY_TARGET_SCOPE,
            target_id=scope_code,
        )
        detail = AdminIdentityDeleteResultPayload.from_result(
            kind=ADMIN_SCOPE_DELETE_RESULT_KIND,
            result=result,
        )
        return self._build_response(
            request=request,
            message=ADMIN_SCOPE_DELETE_SUCCESS_MESSAGE,
            kind=AdminIdentityPayloadKind.SCOPE_DELETE_RESULT,
            operation_name=AdminIdentityOperationName.SCOPE_DELETE,
            detail=detail,
        )

    def _bind_scope_routes(self) -> None:
        """
        绑定 scope 路由。
        """

        self.router.add_api_route(
            ADMIN_SCOPES_PATH,
            self.list_scopes,
            methods=[ADMIN_IDENTITY_METHOD_GET],
            response_model=ResponseEnvelope[AdminIdentityEnvelope],
            dependencies=[Depends(self.require_identity_read)],
        )
        self.router.add_api_route(
            ADMIN_SCOPE_DETAIL_PATH,
            self.get_scope,
            methods=[ADMIN_IDENTITY_METHOD_GET],
            response_model=ResponseEnvelope[AdminIdentityEnvelope],
            dependencies=[Depends(self.require_identity_read)],
        )
        self.router.add_api_route(
            ADMIN_SCOPES_PATH,
            self.create_scope,
            methods=[ADMIN_IDENTITY_METHOD_POST],
            response_model=ResponseEnvelope[AdminIdentityEnvelope],
            dependencies=[Depends(self.require_identity_scope_manage)],
        )
        self.router.add_api_route(
            ADMIN_SCOPE_DETAIL_PATH,
            self.update_scope,
            methods=[ADMIN_IDENTITY_METHOD_PATCH],
            response_model=ResponseEnvelope[AdminIdentityEnvelope],
            dependencies=[Depends(self.require_identity_scope_manage)],
        )
        self.router.add_api_route(
            ADMIN_SCOPE_DETAIL_PATH,
            self.delete_scope,
            methods=[ADMIN_IDENTITY_METHOD_DELETE],
            response_model=ResponseEnvelope[AdminIdentityEnvelope],
            dependencies=[Depends(self.require_identity_scope_manage)],
        )

    def _read_scope_manage_principal(
        self,
        request: Request,
    ) -> AuthenticatedPrincipal:
        """
        读取管理员 scope 管理权限主体。
        """

        return self._accessor.read_authorized_principal(
            request,
            ADMIN_IDENTITY_SCOPE_MANAGE_AUTHORIZATION_REQUIREMENT,
        )
