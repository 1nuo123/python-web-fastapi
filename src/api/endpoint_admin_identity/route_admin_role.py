"""管理员角色路由。"""

from __future__ import annotations

from fastapi import Depends, Path, Query, Request

from src.api.endpoint_admin_identity.contract_admin_identity_common import (
    ADMIN_ROLE_DELETE_RESULT_KIND,
    AdminIdentityDeleteResultPayload,
    AdminIdentityOperationName,
    AdminIdentityPayloadKind,
)
from src.api.endpoint_admin_identity.contract_admin_identity_envelope import (
    AdminIdentityEnvelope,
)
from src.api.endpoint_admin_identity.contract_admin_role import (
    AdminBusinessRoleListPayload,
    AdminRoleCreateRequest,
    AdminRoleListPayload,
    AdminRolePayload,
    AdminRoleScopeReplaceRequest,
    AdminRoleUpdateRequest,
)
from src.api.endpoint_admin_identity.route_admin_identity_common import (
    ADMIN_BUSINESS_ROLES_PATH,
    ADMIN_IDENTITY_KEYWORD_DESCRIPTION,
    ADMIN_IDENTITY_METHOD_DELETE,
    ADMIN_IDENTITY_METHOD_GET,
    ADMIN_IDENTITY_METHOD_PATCH,
    ADMIN_IDENTITY_METHOD_POST,
    ADMIN_IDENTITY_METHOD_PUT,
    ADMIN_IDENTITY_OFFSET_DESCRIPTION,
    ADMIN_IDENTITY_PAGE_SIZE_DESCRIPTION,
    ADMIN_IDENTITY_REQUEST_EXECUTION_NAME,
    ADMIN_IDENTITY_ROLE_KEY_DESCRIPTION,
    ADMIN_IDENTITY_TARGET_ROLE,
    ADMIN_ROLE_CREATE_SUCCESS_MESSAGE,
    ADMIN_ROLE_DELETE_SUCCESS_MESSAGE,
    ADMIN_ROLE_DETAIL_PATH,
    ADMIN_ROLE_DETAIL_SUCCESS_MESSAGE,
    ADMIN_ROLE_LIST_SUCCESS_MESSAGE,
    ADMIN_ROLE_SCOPE_REPLACE_SUCCESS_MESSAGE,
    ADMIN_ROLE_SCOPES_PATH,
    ADMIN_ROLE_UPDATE_SUCCESS_MESSAGE,
    ADMIN_ROLES_PATH,
    AdminIdentityRouteSupport,
)
from src.application.admin.identity.shared.admin_identity_command import (
    AdminRoleCreateCommand,
    AdminRoleDeleteCommand,
    AdminRoleScopeReplaceCommand,
    AdminRoleUpdateCommand,
)
from src.application.ports.admin_identity_port import (
    ADMIN_IDENTITY_QUERY_LIMIT_DEFAULT,
    ADMIN_IDENTITY_QUERY_LIMIT_MAXIMUM,
    ADMIN_IDENTITY_QUERY_LIMIT_MINIMUM,
    ADMIN_IDENTITY_QUERY_OFFSET_MINIMUM,
    AdminRoleListQuery,
)
from src.core.auth_contract.authenticated_principal_contract import (
    AuthenticatedPrincipal,
)
from src.core.http_contract.response_envelope_contract import ResponseEnvelope
from src.domain.auth.admin_route_authorization_policy import (
    ADMIN_IDENTITY_ROLE_MANAGE_AUTHORIZATION_REQUIREMENT,
    PROTECTED_ADMIN_SCOPE_REGISTRY,
)


class AdminRoleRouteCatalog(AdminIdentityRouteSupport):
    """管理员角色路由目录。"""

    async def list_roles(
        self,
        request: Request,
        keyword: str | None = Query(
            default=None,
            description=ADMIN_IDENTITY_KEYWORD_DESCRIPTION,
        ),
        page_size: int = Query(
            default=ADMIN_IDENTITY_QUERY_LIMIT_DEFAULT,
            ge=ADMIN_IDENTITY_QUERY_LIMIT_MINIMUM,
            le=ADMIN_IDENTITY_QUERY_LIMIT_MAXIMUM,
            description=ADMIN_IDENTITY_PAGE_SIZE_DESCRIPTION,
        ),
        offset: int = Query(
            default=ADMIN_IDENTITY_QUERY_OFFSET_MINIMUM,
            ge=ADMIN_IDENTITY_QUERY_OFFSET_MINIMUM,
            description=ADMIN_IDENTITY_OFFSET_DESCRIPTION,
        ),
    ) -> ResponseEnvelope[AdminIdentityEnvelope]:
        """
        查询管理员角色列表。
        """

        page = await self._accessor.read_request_execution_bridge(request).run_sync(
            execution_name=ADMIN_IDENTITY_REQUEST_EXECUTION_NAME,
            callable_object=self._accessor.read_list_admin_roles_usecase(request).execute,
            query=AdminRoleListQuery(
                keyword=keyword,
                page_size=page_size,
                offset=offset,
            ),
        )
        return self._build_response(
            request=request,
            message=ADMIN_ROLE_LIST_SUCCESS_MESSAGE,
            kind=AdminIdentityPayloadKind.ROLE_LIST,
            operation_name=AdminIdentityOperationName.ROLE_LIST,
            detail=AdminRoleListPayload.from_page(page),
        )

    async def list_business_roles(
        self,
        request: Request,
        keyword: str | None = Query(
            default=None,
            description=ADMIN_IDENTITY_KEYWORD_DESCRIPTION,
        ),
        page_size: int = Query(
            default=ADMIN_IDENTITY_QUERY_LIMIT_DEFAULT,
            ge=ADMIN_IDENTITY_QUERY_LIMIT_MINIMUM,
            le=ADMIN_IDENTITY_QUERY_LIMIT_MAXIMUM,
            description=ADMIN_IDENTITY_PAGE_SIZE_DESCRIPTION,
        ),
        offset: int = Query(
            default=ADMIN_IDENTITY_QUERY_OFFSET_MINIMUM,
            ge=ADMIN_IDENTITY_QUERY_OFFSET_MINIMUM,
            description=ADMIN_IDENTITY_OFFSET_DESCRIPTION,
        ),
    ) -> ResponseEnvelope[AdminIdentityEnvelope]:
        """
        查询业务后台可分配角色列表。
        """

        page = await self._accessor.read_request_execution_bridge(request).run_sync(
            execution_name=ADMIN_IDENTITY_REQUEST_EXECUTION_NAME,
            callable_object=self._accessor.read_list_admin_roles_usecase(request).execute,
            query=AdminRoleListQuery(
                keyword=keyword,
                page_size=page_size,
                offset=offset,
                business_only=True,
            ),
        )
        return self._build_response(
            request=request,
            message=ADMIN_ROLE_LIST_SUCCESS_MESSAGE,
            kind=AdminIdentityPayloadKind.BUSINESS_ROLE_LIST,
            operation_name=AdminIdentityOperationName.ROLE_LIST,
            detail=AdminBusinessRoleListPayload.from_page(page),
        )

    async def get_role(
        self,
        request: Request,
        role_key: str = Path(description=ADMIN_IDENTITY_ROLE_KEY_DESCRIPTION),
    ) -> ResponseEnvelope[AdminIdentityEnvelope]:
        """
        读取管理员角色详情。
        """

        snapshot = await self._accessor.read_request_execution_bridge(request).run_sync(
            execution_name=ADMIN_IDENTITY_REQUEST_EXECUTION_NAME,
            callable_object=self._accessor.read_get_admin_role_usecase(request).execute,
            role_key=role_key,
        )
        return self._build_response(
            request=request,
            message=ADMIN_ROLE_DETAIL_SUCCESS_MESSAGE,
            kind=AdminIdentityPayloadKind.ROLE,
            operation_name=AdminIdentityOperationName.ROLE_DETAIL,
            detail=AdminRolePayload.from_snapshot(snapshot),
        )

    async def create_role(
        self,
        request: Request,
        command: AdminIdentityEnvelope,
    ) -> ResponseEnvelope[AdminIdentityEnvelope]:
        """
        创建管理员角色。
        """

        principal = self._read_role_manage_principal(request)
        detail = self._read_detail(command, AdminRoleCreateRequest)
        grant_confirmed = self._role_create_requires_grant_confirmation(detail.scope_codes)
        if grant_confirmed:
            self._assert_grant_confirmation(detail.confirmation)
            principal = self._read_grant_admin_principal(request)
        snapshot = await self._accessor.read_request_execution_bridge(request).run_sync(
            execution_name=ADMIN_IDENTITY_REQUEST_EXECUTION_NAME,
            callable_object=self._accessor.read_create_admin_role_usecase(request).execute,
            command=AdminRoleCreateCommand(
                role_key=detail.role_key,
                role_name=detail.role_name,
                scope_codes=detail.scope_codes,
                grant_confirmed=grant_confirmed,
            ),
        )
        self._record_identity_change(
            request=request,
            principal=principal,
            operation_name=AdminIdentityOperationName.ROLE_CREATE,
            target_kind=ADMIN_IDENTITY_TARGET_ROLE,
            target_id=detail.role_key,
        )
        return self._build_response(
            request=request,
            message=ADMIN_ROLE_CREATE_SUCCESS_MESSAGE,
            kind=AdminIdentityPayloadKind.ROLE,
            operation_name=AdminIdentityOperationName.ROLE_CREATE,
            detail=AdminRolePayload.from_snapshot(snapshot),
        )

    async def update_role(
        self,
        request: Request,
        command: AdminIdentityEnvelope,
        role_key: str = Path(description=ADMIN_IDENTITY_ROLE_KEY_DESCRIPTION),
    ) -> ResponseEnvelope[AdminIdentityEnvelope]:
        """
        更新管理员角色。
        """

        principal = self._read_role_manage_principal(request)
        detail = self._read_detail(command, AdminRoleUpdateRequest)
        snapshot = await self._accessor.read_request_execution_bridge(request).run_sync(
            execution_name=ADMIN_IDENTITY_REQUEST_EXECUTION_NAME,
            callable_object=self._accessor.read_update_admin_role_usecase(request).execute,
            command=AdminRoleUpdateCommand(
                role_key=role_key,
                role_name=detail.role_name,
            ),
        )
        self._record_identity_change(
            request=request,
            principal=principal,
            operation_name=AdminIdentityOperationName.ROLE_UPDATE,
            target_kind=ADMIN_IDENTITY_TARGET_ROLE,
            target_id=role_key,
        )
        return self._build_response(
            request=request,
            message=ADMIN_ROLE_UPDATE_SUCCESS_MESSAGE,
            kind=AdminIdentityPayloadKind.ROLE,
            operation_name=AdminIdentityOperationName.ROLE_UPDATE,
            detail=AdminRolePayload.from_snapshot(snapshot),
        )

    async def replace_role_scopes(
        self,
        request: Request,
        command: AdminIdentityEnvelope,
        role_key: str = Path(description=ADMIN_IDENTITY_ROLE_KEY_DESCRIPTION),
    ) -> ResponseEnvelope[AdminIdentityEnvelope]:
        """
        替换管理员角色 scope。
        """

        principal = self._read_grant_admin_principal(request)
        detail = self._read_detail(command, AdminRoleScopeReplaceRequest)
        self._assert_grant_confirmation(detail.confirmation)
        snapshot = await self._accessor.read_request_execution_bridge(request).run_sync(
            execution_name=ADMIN_IDENTITY_REQUEST_EXECUTION_NAME,
            callable_object=self._accessor.read_replace_admin_role_scopes_usecase(request).execute,
            command=AdminRoleScopeReplaceCommand(
                actor_subject_id=principal.subject_id,
                role_key=role_key,
                scope_codes=detail.scope_codes,
            ),
        )
        self._record_identity_change(
            request=request,
            principal=principal,
            operation_name=AdminIdentityOperationName.ROLE_SCOPE_REPLACE,
            target_kind=ADMIN_IDENTITY_TARGET_ROLE,
            target_id=role_key,
        )
        return self._build_response(
            request=request,
            message=ADMIN_ROLE_SCOPE_REPLACE_SUCCESS_MESSAGE,
            kind=AdminIdentityPayloadKind.ROLE,
            operation_name=AdminIdentityOperationName.ROLE_SCOPE_REPLACE,
            detail=AdminRolePayload.from_snapshot(snapshot),
        )

    async def delete_role(
        self,
        request: Request,
        role_key: str = Path(description=ADMIN_IDENTITY_ROLE_KEY_DESCRIPTION),
    ) -> ResponseEnvelope[AdminIdentityEnvelope]:
        """
        删除管理员角色。
        """

        principal = self._read_role_manage_principal(request)
        result = await self._accessor.read_request_execution_bridge(request).run_sync(
            execution_name=ADMIN_IDENTITY_REQUEST_EXECUTION_NAME,
            callable_object=self._accessor.read_delete_admin_role_usecase(request).execute,
            command=AdminRoleDeleteCommand(
                actor_subject_id=principal.subject_id,
                role_key=role_key,
            ),
        )
        self._record_identity_change(
            request=request,
            principal=principal,
            operation_name=AdminIdentityOperationName.ROLE_DELETE,
            target_kind=ADMIN_IDENTITY_TARGET_ROLE,
            target_id=role_key,
        )
        detail = AdminIdentityDeleteResultPayload.from_result(
            kind=ADMIN_ROLE_DELETE_RESULT_KIND,
            result=result,
        )
        return self._build_response(
            request=request,
            message=ADMIN_ROLE_DELETE_SUCCESS_MESSAGE,
            kind=AdminIdentityPayloadKind.ROLE_DELETE_RESULT,
            operation_name=AdminIdentityOperationName.ROLE_DELETE,
            detail=detail,
        )

    def _bind_role_routes(self) -> None:
        """
        绑定角色路由。
        """

        self.router.add_api_route(
            ADMIN_ROLES_PATH,
            self.list_roles,
            methods=[ADMIN_IDENTITY_METHOD_GET],
            response_model=ResponseEnvelope[AdminIdentityEnvelope],
            dependencies=[Depends(self.require_identity_read)],
        )
        self.router.add_api_route(
            ADMIN_BUSINESS_ROLES_PATH,
            self.list_business_roles,
            methods=[ADMIN_IDENTITY_METHOD_GET],
            response_model=ResponseEnvelope[AdminIdentityEnvelope],
            dependencies=[Depends(self.require_identity_read)],
        )
        self.router.add_api_route(
            ADMIN_ROLE_DETAIL_PATH,
            self.get_role,
            methods=[ADMIN_IDENTITY_METHOD_GET],
            response_model=ResponseEnvelope[AdminIdentityEnvelope],
            dependencies=[Depends(self.require_identity_read)],
        )
        self.router.add_api_route(
            ADMIN_ROLES_PATH,
            self.create_role,
            methods=[ADMIN_IDENTITY_METHOD_POST],
            response_model=ResponseEnvelope[AdminIdentityEnvelope],
            dependencies=[Depends(self.require_identity_role_manage)],
        )
        self.router.add_api_route(
            ADMIN_ROLE_DETAIL_PATH,
            self.update_role,
            methods=[ADMIN_IDENTITY_METHOD_PATCH],
            response_model=ResponseEnvelope[AdminIdentityEnvelope],
            dependencies=[Depends(self.require_identity_role_manage)],
        )
        self.router.add_api_route(
            ADMIN_ROLE_SCOPES_PATH,
            self.replace_role_scopes,
            methods=[ADMIN_IDENTITY_METHOD_PUT],
            response_model=ResponseEnvelope[AdminIdentityEnvelope],
            dependencies=[Depends(self.require_identity_grant_admin)],
        )
        self.router.add_api_route(
            ADMIN_ROLE_DETAIL_PATH,
            self.delete_role,
            methods=[ADMIN_IDENTITY_METHOD_DELETE],
            response_model=ResponseEnvelope[AdminIdentityEnvelope],
            dependencies=[Depends(self.require_identity_role_manage)],
        )

    def _role_create_requires_grant_confirmation(
        self,
        scope_codes: list[str],
    ) -> bool:
        """
        判断角色创建是否包含受保护后台授权 scope。
        """

        return any(
            PROTECTED_ADMIN_SCOPE_REGISTRY.contains(scope_code) for scope_code in scope_codes
        )

    def _read_role_manage_principal(
        self,
        request: Request,
    ) -> AuthenticatedPrincipal:
        """
        读取管理员角色管理权限主体。
        """

        return self._accessor.read_authorized_principal(
            request,
            ADMIN_IDENTITY_ROLE_MANAGE_AUTHORIZATION_REQUIREMENT,
        )
