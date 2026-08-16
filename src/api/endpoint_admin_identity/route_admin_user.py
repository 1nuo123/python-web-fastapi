"""管理员用户路由。"""

from __future__ import annotations

from fastapi import Depends, Path, Query, Request

from src.api.endpoint_admin_identity.contract_admin_identity_common import (
    AdminIdentityOperationName,
    AdminIdentityPayloadKind,
)
from src.api.endpoint_admin_identity.contract_admin_identity_envelope import (
    AdminIdentityEnvelope,
)
from src.api.endpoint_admin_identity.contract_admin_user import (
    AdminUserCreateRequest,
    AdminUserDisableRequest,
    AdminUserEnableRequest,
    AdminUserListPayload,
    AdminUserPasswordResetRequest,
    AdminUserPayload,
    AdminUserRoleReplaceRequest,
    AdminUserScopeReplaceRequest,
    AdminUserStatusResultPayload,
    AdminUserUpdateRequest,
)
from src.api.endpoint_admin_identity.route_admin_identity_common import (
    ADMIN_IDENTITY_ACTIVE_DESCRIPTION,
    ADMIN_IDENTITY_KEYWORD_DESCRIPTION,
    ADMIN_IDENTITY_METHOD_GET,
    ADMIN_IDENTITY_METHOD_PATCH,
    ADMIN_IDENTITY_METHOD_POST,
    ADMIN_IDENTITY_METHOD_PUT,
    ADMIN_IDENTITY_OFFSET_DESCRIPTION,
    ADMIN_IDENTITY_PAGE_SIZE_DESCRIPTION,
    ADMIN_IDENTITY_REQUEST_EXECUTION_NAME,
    ADMIN_IDENTITY_ROLE_KEY_DESCRIPTION,
    ADMIN_IDENTITY_SUBJECT_ID_DESCRIPTION,
    ADMIN_IDENTITY_TARGET_USER,
    ADMIN_USER_CREATE_SUCCESS_MESSAGE,
    ADMIN_USER_DETAIL_PATH,
    ADMIN_USER_DETAIL_SUCCESS_MESSAGE,
    ADMIN_USER_DISABLE_PATH,
    ADMIN_USER_DISABLE_SUCCESS_MESSAGE,
    ADMIN_USER_ENABLE_PATH,
    ADMIN_USER_ENABLE_SUCCESS_MESSAGE,
    ADMIN_USER_LIST_SUCCESS_MESSAGE,
    ADMIN_USER_PASSWORD_PATH,
    ADMIN_USER_PASSWORD_RESET_SUCCESS_MESSAGE,
    ADMIN_USER_ROLE_REPLACE_SUCCESS_MESSAGE,
    ADMIN_USER_ROLES_PATH,
    ADMIN_USER_SCOPE_REPLACE_SUCCESS_MESSAGE,
    ADMIN_USER_SCOPES_PATH,
    ADMIN_USER_UPDATE_SUCCESS_MESSAGE,
    ADMIN_USERS_PATH,
    AdminIdentityRouteSupport,
)
from src.application.admin.identity.shared.admin_identity_command import (
    AdminUserCreateCommand,
    AdminUserDeleteCommand,
    AdminUserPasswordResetCommand,
    AdminUserRoleReplaceCommand,
    AdminUserScopeReplaceCommand,
    AdminUserUpdateCommand,
)
from src.application.ports.admin_identity_port import (
    ADMIN_IDENTITY_QUERY_LIMIT_DEFAULT,
    ADMIN_IDENTITY_QUERY_LIMIT_MAXIMUM,
    ADMIN_IDENTITY_QUERY_LIMIT_MINIMUM,
    ADMIN_IDENTITY_QUERY_OFFSET_MINIMUM,
    AdminUserListQuery,
)
from src.core.auth_contract.authenticated_principal_contract import (
    AuthenticatedPrincipal,
)
from src.core.http_contract.response_envelope_contract import ResponseEnvelope
from src.domain.auth.admin_route_authorization_policy import (
    ADMIN_IDENTITY_PASSWORD_RESET_AUTHORIZATION_REQUIREMENT,
    ADMIN_IDENTITY_USER_MANAGE_AUTHORIZATION_REQUIREMENT,
)


class AdminUserRouteCatalog(AdminIdentityRouteSupport):
    """管理员用户路由目录。"""

    async def list_users(
        self,
        request: Request,
        keyword: str | None = Query(
            default=None,
            description=ADMIN_IDENTITY_KEYWORD_DESCRIPTION,
        ),
        role_key: str | None = Query(
            default=None,
            description=ADMIN_IDENTITY_ROLE_KEY_DESCRIPTION,
        ),
        is_active: bool | None = Query(
            default=None,
            description=ADMIN_IDENTITY_ACTIVE_DESCRIPTION,
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
        查询管理员用户列表。
        """

        page = await self._accessor.read_request_execution_bridge(request).run_sync(
            execution_name=ADMIN_IDENTITY_REQUEST_EXECUTION_NAME,
            callable_object=self._accessor.read_list_admin_users_usecase(request).execute,
            query=AdminUserListQuery(
                keyword=keyword,
                role_key=role_key,
                is_active=is_active,
                page_size=page_size,
                offset=offset,
            ),
        )
        return self._build_response(
            request=request,
            message=ADMIN_USER_LIST_SUCCESS_MESSAGE,
            kind=AdminIdentityPayloadKind.USER_LIST,
            operation_name=AdminIdentityOperationName.USER_LIST,
            detail=AdminUserListPayload.from_page(page),
        )

    async def get_user(
        self,
        request: Request,
        subject_id: str = Path(description=ADMIN_IDENTITY_SUBJECT_ID_DESCRIPTION),
    ) -> ResponseEnvelope[AdminIdentityEnvelope]:
        """
        读取管理员用户详情。
        """

        snapshot = await self._accessor.read_request_execution_bridge(request).run_sync(
            execution_name=ADMIN_IDENTITY_REQUEST_EXECUTION_NAME,
            callable_object=self._accessor.read_get_admin_user_usecase(request).execute,
            subject_id=subject_id,
        )
        return self._build_response(
            request=request,
            message=ADMIN_USER_DETAIL_SUCCESS_MESSAGE,
            kind=AdminIdentityPayloadKind.USER,
            operation_name=AdminIdentityOperationName.USER_DETAIL,
            detail=AdminUserPayload.from_snapshot(snapshot),
        )

    async def create_user(
        self,
        request: Request,
        command: AdminIdentityEnvelope,
    ) -> ResponseEnvelope[AdminIdentityEnvelope]:
        """
        创建管理员用户。
        """

        principal = self._read_user_manage_principal(request)
        detail = self._read_detail(command, AdminUserCreateRequest)
        snapshot = await self._accessor.read_request_execution_bridge(request).run_sync(
            execution_name=ADMIN_IDENTITY_REQUEST_EXECUTION_NAME,
            callable_object=self._accessor.read_create_admin_user_usecase(request).execute,
            command=AdminUserCreateCommand(
                username=detail.username,
                password_plain=detail.password.get_secret_value(),
                role_keys=detail.role_keys,
                subject_id=detail.subject_id,
            ),
        )
        user_payload = AdminUserPayload.from_snapshot(snapshot)
        self._record_identity_change(
            request=request,
            principal=principal,
            operation_name=AdminIdentityOperationName.USER_CREATE,
            target_kind=ADMIN_IDENTITY_TARGET_USER,
            target_id=user_payload.subject_id,
        )
        return self._build_response(
            request=request,
            message=ADMIN_USER_CREATE_SUCCESS_MESSAGE,
            kind=AdminIdentityPayloadKind.USER,
            operation_name=AdminIdentityOperationName.USER_CREATE,
            detail=user_payload,
        )

    async def update_user(
        self,
        request: Request,
        command: AdminIdentityEnvelope,
        subject_id: str = Path(description=ADMIN_IDENTITY_SUBJECT_ID_DESCRIPTION),
    ) -> ResponseEnvelope[AdminIdentityEnvelope]:
        """
        更新管理员用户。
        """

        principal = self._read_user_manage_principal(request)
        detail = self._read_detail(command, AdminUserUpdateRequest)
        snapshot = await self._accessor.read_request_execution_bridge(request).run_sync(
            execution_name=ADMIN_IDENTITY_REQUEST_EXECUTION_NAME,
            callable_object=self._accessor.read_update_admin_user_usecase(request).execute,
            command=AdminUserUpdateCommand(
                actor_subject_id=principal.subject_id,
                subject_id=subject_id,
                username=detail.username,
                is_active=None,
            ),
        )
        self._record_identity_change(
            request=request,
            principal=principal,
            operation_name=AdminIdentityOperationName.USER_UPDATE,
            target_kind=ADMIN_IDENTITY_TARGET_USER,
            target_id=subject_id,
        )
        return self._build_response(
            request=request,
            message=ADMIN_USER_UPDATE_SUCCESS_MESSAGE,
            kind=AdminIdentityPayloadKind.USER,
            operation_name=AdminIdentityOperationName.USER_UPDATE,
            detail=AdminUserPayload.from_snapshot(snapshot),
        )

    async def reset_user_password(
        self,
        request: Request,
        command: AdminIdentityEnvelope,
        subject_id: str = Path(description=ADMIN_IDENTITY_SUBJECT_ID_DESCRIPTION),
    ) -> ResponseEnvelope[AdminIdentityEnvelope]:
        """
        重置管理员用户密码。
        """

        principal = self._read_password_reset_principal(request)
        detail = self._read_detail(command, AdminUserPasswordResetRequest)
        snapshot = await self._accessor.read_request_execution_bridge(request).run_sync(
            execution_name=ADMIN_IDENTITY_REQUEST_EXECUTION_NAME,
            callable_object=self._accessor.read_reset_admin_user_password_usecase(request).execute,
            command=AdminUserPasswordResetCommand(
                actor_subject_id=principal.subject_id,
                subject_id=subject_id,
                password_plain=detail.password.get_secret_value(),
            ),
        )
        self._record_identity_change(
            request=request,
            principal=principal,
            operation_name=AdminIdentityOperationName.USER_PASSWORD_RESET,
            target_kind=ADMIN_IDENTITY_TARGET_USER,
            target_id=subject_id,
        )
        return self._build_response(
            request=request,
            message=ADMIN_USER_PASSWORD_RESET_SUCCESS_MESSAGE,
            kind=AdminIdentityPayloadKind.USER,
            operation_name=AdminIdentityOperationName.USER_PASSWORD_RESET,
            detail=AdminUserPayload.from_snapshot(snapshot),
        )

    async def replace_user_roles(
        self,
        request: Request,
        command: AdminIdentityEnvelope,
        subject_id: str = Path(description=ADMIN_IDENTITY_SUBJECT_ID_DESCRIPTION),
    ) -> ResponseEnvelope[AdminIdentityEnvelope]:
        """
        替换管理员用户角色。
        """

        principal = self._read_grant_admin_principal(request)
        detail = self._read_detail(command, AdminUserRoleReplaceRequest)
        self._assert_grant_confirmation(detail.confirmation)
        snapshot = await self._accessor.read_request_execution_bridge(request).run_sync(
            execution_name=ADMIN_IDENTITY_REQUEST_EXECUTION_NAME,
            callable_object=self._accessor.read_replace_admin_user_roles_usecase(request).execute,
            command=AdminUserRoleReplaceCommand(
                actor_subject_id=principal.subject_id,
                subject_id=subject_id,
                role_keys=detail.role_keys,
            ),
        )
        self._record_identity_change(
            request=request,
            principal=principal,
            operation_name=AdminIdentityOperationName.USER_ROLE_REPLACE,
            target_kind=ADMIN_IDENTITY_TARGET_USER,
            target_id=subject_id,
        )
        return self._build_response(
            request=request,
            message=ADMIN_USER_ROLE_REPLACE_SUCCESS_MESSAGE,
            kind=AdminIdentityPayloadKind.USER,
            operation_name=AdminIdentityOperationName.USER_ROLE_REPLACE,
            detail=AdminUserPayload.from_snapshot(snapshot),
        )

    async def replace_user_scopes(
        self,
        request: Request,
        command: AdminIdentityEnvelope,
        subject_id: str = Path(description=ADMIN_IDENTITY_SUBJECT_ID_DESCRIPTION),
    ) -> ResponseEnvelope[AdminIdentityEnvelope]:
        """替换管理员用户直接 scope。"""

        principal = self._read_grant_admin_principal(request)
        detail = self._read_detail(command, AdminUserScopeReplaceRequest)
        self._assert_grant_confirmation(detail.confirmation)
        snapshot = await self._accessor.read_request_execution_bridge(request).run_sync(
            execution_name=ADMIN_IDENTITY_REQUEST_EXECUTION_NAME,
            callable_object=self._accessor.read_replace_admin_user_scopes_usecase(request).execute,
            command=AdminUserScopeReplaceCommand(
                actor_subject_id=principal.subject_id,
                subject_id=subject_id,
                scope_codes=detail.scope_codes,
            ),
        )
        self._record_identity_change(
            request=request,
            principal=principal,
            operation_name=AdminIdentityOperationName.USER_SCOPE_REPLACE,
            target_kind=ADMIN_IDENTITY_TARGET_USER,
            target_id=subject_id,
        )
        return self._build_response(
            request=request,
            message=ADMIN_USER_SCOPE_REPLACE_SUCCESS_MESSAGE,
            kind=AdminIdentityPayloadKind.USER,
            operation_name=AdminIdentityOperationName.USER_SCOPE_REPLACE,
            detail=AdminUserPayload.from_snapshot(snapshot),
        )

    async def disable_user(
        self,
        request: Request,
        command: AdminIdentityEnvelope,
        subject_id: str = Path(description=ADMIN_IDENTITY_SUBJECT_ID_DESCRIPTION),
    ) -> ResponseEnvelope[AdminIdentityEnvelope]:
        """
        停用管理员用户。
        """

        principal = self._read_user_manage_principal(request)
        detail = self._read_detail(command, AdminUserDisableRequest)
        result = await self._accessor.read_request_execution_bridge(request).run_sync(
            execution_name=ADMIN_IDENTITY_REQUEST_EXECUTION_NAME,
            callable_object=self._accessor.read_delete_admin_user_usecase(request).execute,
            command=AdminUserDeleteCommand(
                actor_subject_id=principal.subject_id,
                subject_id=subject_id,
                reason=detail.reason,
            ),
        )
        await self._accessor.read_revoke_codex_subject_agent_access_usecase(request).execute(
            subject_id=subject_id
        )
        self._record_identity_change(
            request=request,
            principal=principal,
            operation_name=AdminIdentityOperationName.USER_DISABLE,
            target_kind=ADMIN_IDENTITY_TARGET_USER,
            target_id=subject_id,
        )
        return self._build_response(
            request=request,
            message=ADMIN_USER_DISABLE_SUCCESS_MESSAGE,
            kind=AdminIdentityPayloadKind.USER_STATUS_RESULT,
            operation_name=AdminIdentityOperationName.USER_DISABLE,
            detail=AdminUserStatusResultPayload.from_disabled_result(result),
        )

    async def enable_user(
        self,
        request: Request,
        command: AdminIdentityEnvelope,
        subject_id: str = Path(description=ADMIN_IDENTITY_SUBJECT_ID_DESCRIPTION),
    ) -> ResponseEnvelope[AdminIdentityEnvelope]:
        """
        启用管理员用户。
        """

        principal = self._read_user_manage_principal(request)
        detail = self._read_detail(command, AdminUserEnableRequest)
        snapshot = await self._accessor.read_request_execution_bridge(request).run_sync(
            execution_name=ADMIN_IDENTITY_REQUEST_EXECUTION_NAME,
            callable_object=self._accessor.read_update_admin_user_usecase(request).execute,
            command=AdminUserUpdateCommand(
                actor_subject_id=principal.subject_id,
                subject_id=subject_id,
                username=None,
                is_active=True,
            ),
        )
        self._record_identity_change(
            request=request,
            principal=principal,
            operation_name=AdminIdentityOperationName.USER_ENABLE,
            target_kind=ADMIN_IDENTITY_TARGET_USER,
            target_id=subject_id,
        )
        return self._build_response(
            request=request,
            message=ADMIN_USER_ENABLE_SUCCESS_MESSAGE,
            kind=AdminIdentityPayloadKind.USER_STATUS_RESULT,
            operation_name=AdminIdentityOperationName.USER_ENABLE,
            detail=AdminUserStatusResultPayload.from_enabled_snapshot(
                snapshot,
                reason=detail.reason,
            ),
        )

    def _bind_user_routes(self) -> None:
        """
        绑定用户路由。
        """

        self.router.add_api_route(
            ADMIN_USERS_PATH,
            self.list_users,
            methods=[ADMIN_IDENTITY_METHOD_GET],
            response_model=ResponseEnvelope[AdminIdentityEnvelope],
            dependencies=[Depends(self.require_identity_read)],
        )
        self.router.add_api_route(
            ADMIN_USER_DETAIL_PATH,
            self.get_user,
            methods=[ADMIN_IDENTITY_METHOD_GET],
            response_model=ResponseEnvelope[AdminIdentityEnvelope],
            dependencies=[Depends(self.require_identity_read)],
        )
        self.router.add_api_route(
            ADMIN_USERS_PATH,
            self.create_user,
            methods=[ADMIN_IDENTITY_METHOD_POST],
            response_model=ResponseEnvelope[AdminIdentityEnvelope],
            dependencies=[Depends(self.require_identity_user_manage)],
        )
        self.router.add_api_route(
            ADMIN_USER_DETAIL_PATH,
            self.update_user,
            methods=[ADMIN_IDENTITY_METHOD_PATCH],
            response_model=ResponseEnvelope[AdminIdentityEnvelope],
            dependencies=[Depends(self.require_identity_user_manage)],
        )
        self.router.add_api_route(
            ADMIN_USER_PASSWORD_PATH,
            self.reset_user_password,
            methods=[ADMIN_IDENTITY_METHOD_POST],
            response_model=ResponseEnvelope[AdminIdentityEnvelope],
            dependencies=[Depends(self.require_identity_password_reset)],
        )
        self.router.add_api_route(
            ADMIN_USER_DISABLE_PATH,
            self.disable_user,
            methods=[ADMIN_IDENTITY_METHOD_POST],
            response_model=ResponseEnvelope[AdminIdentityEnvelope],
            dependencies=[Depends(self.require_identity_user_manage)],
        )
        self.router.add_api_route(
            ADMIN_USER_ENABLE_PATH,
            self.enable_user,
            methods=[ADMIN_IDENTITY_METHOD_POST],
            response_model=ResponseEnvelope[AdminIdentityEnvelope],
            dependencies=[Depends(self.require_identity_user_manage)],
        )
        self.router.add_api_route(
            ADMIN_USER_ROLES_PATH,
            self.replace_user_roles,
            methods=[ADMIN_IDENTITY_METHOD_POST],
            response_model=ResponseEnvelope[AdminIdentityEnvelope],
            dependencies=[Depends(self.require_identity_grant_admin)],
        )
        self.router.add_api_route(
            ADMIN_USER_SCOPES_PATH,
            self.replace_user_scopes,
            methods=[ADMIN_IDENTITY_METHOD_PUT],
            response_model=ResponseEnvelope[AdminIdentityEnvelope],
            dependencies=[Depends(self.require_identity_grant_admin)],
        )

    def _read_password_reset_principal(
        self,
        request: Request,
    ) -> AuthenticatedPrincipal:
        """
        读取管理员密码重置权限主体。
        """

        return self._accessor.read_authorized_principal(
            request,
            ADMIN_IDENTITY_PASSWORD_RESET_AUTHORIZATION_REQUIREMENT,
        )

    def _read_user_manage_principal(
        self,
        request: Request,
    ) -> AuthenticatedPrincipal:
        """
        读取管理员用户管理权限主体。
        """

        return self._accessor.read_authorized_principal(
            request,
            ADMIN_IDENTITY_USER_MANAGE_AUTHORIZATION_REQUIREMENT,
        )
