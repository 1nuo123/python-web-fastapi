"""管理员身份路由公共支持。"""

from __future__ import annotations

from http import HTTPStatus
from typing import TypeVar

from fastapi import APIRouter, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from src.api.dependency_context_accessor import DependencyContextAccessor
from src.api.endpoint_admin_identity.contract_admin_identity_common import (
    ADMIN_IDENTITY_GRANT_CONFIRMATION_INVALID_MESSAGE,
    ADMIN_IDENTITY_GRANT_CONFIRMATION_PHRASE,
    ADMIN_IDENTITY_SCHEMA_VERSION,
    AdminIdentityHeader,
    AdminIdentityOperationName,
    AdminIdentityPayloadKind,
)
from src.api.endpoint_admin_identity.contract_admin_identity_envelope import (
    AdminIdentityDetailUnion,
    AdminIdentityEnvelope,
)
from src.core.auth_contract.authenticated_principal_contract import (
    AuthenticatedPrincipal,
)
from src.core.exception_contract.error_code_catalog_contract import (
    CoreErrorCode,
    SuccessCode,
)
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.http_contract.request_execution_contract import (
    DEFAULT_SYNC_REQUEST_EXECUTION_NAME,
)
from src.core.http_contract.response_envelope_contract import ResponseEnvelope
from src.domain.auth.admin_route_authorization_policy import (
    ADMIN_IDENTITY_GRANT_ADMIN_AUTHORIZATION_REQUIREMENT,
    ADMIN_IDENTITY_PASSWORD_RESET_AUTHORIZATION_REQUIREMENT,
    ADMIN_IDENTITY_READ_AUTHORIZATION_REQUIREMENT,
    ADMIN_IDENTITY_ROLE_MANAGE_AUTHORIZATION_REQUIREMENT,
    ADMIN_IDENTITY_SCOPE_MANAGE_AUTHORIZATION_REQUIREMENT,
    ADMIN_IDENTITY_USER_MANAGE_AUTHORIZATION_REQUIREMENT,
)

ADMIN_IDENTITY_ROUTE_TAG = "admin_identity"

ADMIN_SCOPES_PATH = "/admin/scopes"

ADMIN_SCOPE_DETAIL_PATH = "/admin/scopes/{scope_code}"

ADMIN_ROLES_PATH = "/admin/roles"

ADMIN_BUSINESS_ROLES_PATH = "/admin/business-roles"

ADMIN_ROLE_DETAIL_PATH = "/admin/roles/{role_key}"

ADMIN_ROLE_SCOPES_PATH = "/admin/roles/{role_key}/scopes"

ADMIN_USERS_PATH = "/admin/users"

ADMIN_USER_DETAIL_PATH = "/admin/users/{subject_id}"

ADMIN_USER_DISABLE_PATH = "/admin/users/{subject_id}/disable"

ADMIN_USER_ENABLE_PATH = "/admin/users/{subject_id}/enable"

ADMIN_USER_PASSWORD_PATH = "/admin/users/{subject_id}/password"

ADMIN_USER_ROLES_PATH = "/admin/users/{subject_id}/roles"

ADMIN_USER_SCOPES_PATH = "/admin/users/{subject_id}/scopes"

ADMIN_IDENTITY_METHOD_GET = "GET"

ADMIN_IDENTITY_METHOD_POST = "POST"

ADMIN_IDENTITY_METHOD_PATCH = "PATCH"

ADMIN_IDENTITY_METHOD_PUT = "PUT"

ADMIN_IDENTITY_METHOD_DELETE = "DELETE"

ADMIN_IDENTITY_REQUEST_EXECUTION_NAME = DEFAULT_SYNC_REQUEST_EXECUTION_NAME

ADMIN_IDENTITY_BEARER_SCHEME = HTTPBearer(auto_error=False)

ADMIN_IDENTITY_LIMIT_DESCRIPTION = "返回记录数量上限。"

ADMIN_IDENTITY_PAGE_SIZE_DESCRIPTION = "分页大小。"

ADMIN_IDENTITY_OFFSET_DESCRIPTION = "分页偏移。"

ADMIN_IDENTITY_KEYWORD_DESCRIPTION = "关键字过滤。"

ADMIN_IDENTITY_ENABLED_DESCRIPTION = "启用状态过滤。"

ADMIN_IDENTITY_ROLE_KEY_DESCRIPTION = "角色键。"

ADMIN_IDENTITY_SCOPE_CODE_DESCRIPTION = "scope 编码。"

ADMIN_IDENTITY_SUBJECT_ID_DESCRIPTION = "用户主体标识。"

ADMIN_IDENTITY_ACTIVE_DESCRIPTION = "用户启用状态过滤。"

ADMIN_IDENTITY_DETAIL_TYPE_INVALID_MESSAGE = "管理员身份请求载荷类型与当前接口不匹配。"

ADMIN_SCOPE_LIST_SUCCESS_MESSAGE = "管理员 scope 列表查询成功。"

ADMIN_SCOPE_DETAIL_SUCCESS_MESSAGE = "管理员 scope 详情读取成功。"

ADMIN_SCOPE_CREATE_SUCCESS_MESSAGE = "管理员 scope 创建成功。"

ADMIN_SCOPE_UPDATE_SUCCESS_MESSAGE = "管理员 scope 更新成功。"

ADMIN_SCOPE_DELETE_SUCCESS_MESSAGE = "管理员 scope 删除成功。"

ADMIN_ROLE_LIST_SUCCESS_MESSAGE = "管理员角色列表查询成功。"

ADMIN_ROLE_DETAIL_SUCCESS_MESSAGE = "管理员角色详情读取成功。"

ADMIN_ROLE_CREATE_SUCCESS_MESSAGE = "管理员角色创建成功。"

ADMIN_ROLE_UPDATE_SUCCESS_MESSAGE = "管理员角色更新成功。"

ADMIN_ROLE_SCOPE_REPLACE_SUCCESS_MESSAGE = "管理员角色 scope 替换成功。"

ADMIN_ROLE_DELETE_SUCCESS_MESSAGE = "管理员角色删除成功。"

ADMIN_USER_LIST_SUCCESS_MESSAGE = "管理员用户列表查询成功。"

ADMIN_USER_DETAIL_SUCCESS_MESSAGE = "管理员用户详情读取成功。"

ADMIN_USER_CREATE_SUCCESS_MESSAGE = "管理员用户创建成功。"

ADMIN_USER_UPDATE_SUCCESS_MESSAGE = "管理员用户更新成功。"

ADMIN_USER_PASSWORD_RESET_SUCCESS_MESSAGE = "管理员用户密码重置成功。"

ADMIN_USER_ROLE_REPLACE_SUCCESS_MESSAGE = "管理员用户角色替换成功。"

ADMIN_USER_SCOPE_REPLACE_SUCCESS_MESSAGE = "管理员用户直接 scope 替换成功。"

ADMIN_USER_DISABLE_SUCCESS_MESSAGE = "管理员用户停用成功。"

ADMIN_USER_ENABLE_SUCCESS_MESSAGE = "管理员用户启用成功。"

ADMIN_IDENTITY_TARGET_SCOPE = "scope"

ADMIN_IDENTITY_TARGET_ROLE = "role"

ADMIN_IDENTITY_TARGET_USER = "user"

T_AdminIdentityDetail = TypeVar("T_AdminIdentityDetail", bound=BaseModel)


class AdminIdentityRouteSupport:
    """管理员身份路由公共支持。"""

    def __init__(self) -> None:
        """初始化管理员身份路由公共支持。

        :returns: 无返回值。
        :rtype: None
        """

        self._accessor = DependencyContextAccessor()
        self.router = APIRouter(tags=[ADMIN_IDENTITY_ROUTE_TAG])

    async def require_identity_read(
        self,
        request: Request,
        _credentials: HTTPAuthorizationCredentials | None = Security(ADMIN_IDENTITY_BEARER_SCHEME),
    ) -> None:
        """
        校验管理员身份读取权限。
        """

        self._accessor.read_authorized_principal(
            request,
            ADMIN_IDENTITY_READ_AUTHORIZATION_REQUIREMENT,
        )

    async def require_identity_user_manage(
        self,
        request: Request,
        _credentials: HTTPAuthorizationCredentials | None = Security(ADMIN_IDENTITY_BEARER_SCHEME),
    ) -> None:
        """
        校验管理员用户管理权限。
        """

        self._accessor.read_authorized_principal(
            request,
            ADMIN_IDENTITY_USER_MANAGE_AUTHORIZATION_REQUIREMENT,
        )

    async def require_identity_role_manage(
        self,
        request: Request,
        _credentials: HTTPAuthorizationCredentials | None = Security(ADMIN_IDENTITY_BEARER_SCHEME),
    ) -> None:
        """
        校验管理员角色管理权限。
        """

        self._accessor.read_authorized_principal(
            request,
            ADMIN_IDENTITY_ROLE_MANAGE_AUTHORIZATION_REQUIREMENT,
        )

    async def require_identity_scope_manage(
        self,
        request: Request,
        _credentials: HTTPAuthorizationCredentials | None = Security(ADMIN_IDENTITY_BEARER_SCHEME),
    ) -> None:
        """
        校验管理员 scope 管理权限。
        """

        self._accessor.read_authorized_principal(
            request,
            ADMIN_IDENTITY_SCOPE_MANAGE_AUTHORIZATION_REQUIREMENT,
        )

    async def require_identity_password_reset(
        self,
        request: Request,
        _credentials: HTTPAuthorizationCredentials | None = Security(ADMIN_IDENTITY_BEARER_SCHEME),
    ) -> None:
        """
        校验管理员密码重置权限。
        """

        self._accessor.read_authorized_principal(
            request,
            ADMIN_IDENTITY_PASSWORD_RESET_AUTHORIZATION_REQUIREMENT,
        )

    async def require_identity_grant_admin(
        self,
        request: Request,
        _credentials: HTTPAuthorizationCredentials | None = Security(ADMIN_IDENTITY_BEARER_SCHEME),
    ) -> None:
        """
        校验管理员授权变更权限。
        """

        self._accessor.read_authorized_principal(
            request,
            ADMIN_IDENTITY_GRANT_ADMIN_AUTHORIZATION_REQUIREMENT,
        )

    def _read_detail(
        self,
        envelope: AdminIdentityEnvelope,
        detail_type: type[T_AdminIdentityDetail],
    ) -> T_AdminIdentityDetail:
        """
        读取并校验当前接口期望的请求扩展字段。
        """

        if not isinstance(envelope.detail, detail_type):
            raise HttpFaultException(
                status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
                error_code=CoreErrorCode.REQUEST_INVALID,
                message=ADMIN_IDENTITY_DETAIL_TYPE_INVALID_MESSAGE,
            )
        return envelope.detail

    def _assert_grant_confirmation(self, confirmation: str | None) -> None:
        """
        校验高危授权变更二次确认短语。

        :param confirmation: 调用方提交的确认短语。
        :type confirmation: str
        :returns: 无返回值。
        :rtype: None
        :raises HttpFaultException: 当确认短语不匹配时抛出请求无效异常。
        """

        if confirmation != ADMIN_IDENTITY_GRANT_CONFIRMATION_PHRASE:
            raise HttpFaultException(
                status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
                error_code=CoreErrorCode.REQUEST_INVALID,
                message=ADMIN_IDENTITY_GRANT_CONFIRMATION_INVALID_MESSAGE,
            )

    def _build_response(
        self,
        *,
        request: Request,
        message: str,
        kind: AdminIdentityPayloadKind,
        operation_name: AdminIdentityOperationName,
        detail: AdminIdentityDetailUnion,
    ) -> ResponseEnvelope[AdminIdentityEnvelope]:
        """
        构建管理员身份统一响应。
        """

        return self._accessor.read_response_factory(request).build(
            code=str(SuccessCode.OK),
            message=message,
            request_scope=self._accessor.read_request_scope(request),
            data=AdminIdentityEnvelope(
                header=AdminIdentityHeader(
                    kind=kind,
                    schema_version=ADMIN_IDENTITY_SCHEMA_VERSION,
                    operation_name=operation_name,
                ),
                detail=detail,
            ),
        )

    def _read_grant_admin_principal(
        self,
        request: Request,
    ) -> AuthenticatedPrincipal:
        """读取管理员授权变更权限主体。"""

        return self._accessor.read_authorized_principal(
            request,
            ADMIN_IDENTITY_GRANT_ADMIN_AUTHORIZATION_REQUIREMENT,
        )

    def _record_identity_change(
        self,
        *,
        request: Request,
        principal: AuthenticatedPrincipal,
        operation_name: AdminIdentityOperationName,
        target_kind: str,
        target_id: str,
    ) -> None:
        """
        记录管理员身份变更安全事件。
        """

        resource_mount = request.app.state.container.resource_mount
        resource_mount.emit_security_event(
            resource_mount.get_security_event_builder().build_admin_identity_changed_event(
                request=request,
                actor_subject_id=principal.subject_id,
                operation_name=operation_name.value,
                target_kind=target_kind,
                target_id=target_id,
                status_code=HTTPStatus.OK,
            )
        )
