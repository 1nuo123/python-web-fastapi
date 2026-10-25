"""
依赖上下文访问器 API 接口层模块。
"""

from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING, cast

from fastapi import Request

from src.application.admin.apply_admin_settings_reload_usecase import (
    ApplyAdminSettingsReloadUsecase,
)
from src.application.admin.audit.list_admin_audit_events_usecase import (
    ListAdminAuditEventsUsecase,
)
from src.application.admin.build_admin_settings_reload_candidate_usecase import (
    BuildAdminSettingsReloadCandidateUsecase,
)
from src.application.admin.dispatch_admin_task_usecase import DispatchAdminTaskUsecase
from src.application.admin.get_admin_task_execution_record_usecase import (
    GetAdminTaskExecutionRecordUsecase,
)
from src.application.admin.identity.role.create_admin_role_usecase import (
    CreateAdminRoleUsecase,
)
from src.application.admin.identity.role.delete_admin_role_usecase import (
    DeleteAdminRoleUsecase,
)
from src.application.admin.identity.role.get_admin_role_usecase import (
    GetAdminRoleUsecase,
)
from src.application.admin.identity.role.list_admin_roles_usecase import (
    ListAdminRolesUsecase,
)
from src.application.admin.identity.role.replace_admin_role_scopes_usecase import (
    ReplaceAdminRoleScopesUsecase,
)
from src.application.admin.identity.role.update_admin_role_usecase import (
    UpdateAdminRoleUsecase,
)
from src.application.admin.identity.scope.create_admin_scope_usecase import (
    CreateAdminScopeUsecase,
)
from src.application.admin.identity.scope.delete_admin_scope_usecase import (
    DeleteAdminScopeUsecase,
)
from src.application.admin.identity.scope.get_admin_scope_usecase import (
    GetAdminScopeUsecase,
)
from src.application.admin.identity.scope.list_admin_scopes_usecase import (
    ListAdminScopesUsecase,
)
from src.application.admin.identity.scope.update_admin_scope_usecase import (
    UpdateAdminScopeUsecase,
)
from src.application.admin.identity.user.create_admin_user_usecase import (
    CreateAdminUserUsecase,
)
from src.application.admin.identity.user.delete_admin_user_usecase import (
    DeleteAdminUserUsecase,
)
from src.application.admin.identity.user.get_admin_user_usecase import (
    GetAdminUserUsecase,
)
from src.application.admin.identity.user.list_admin_users_usecase import (
    ListAdminUsersUsecase,
)
from src.application.admin.identity.user.replace_admin_user_roles_usecase import (
    ReplaceAdminUserRolesUsecase,
)
from src.application.admin.identity.user.replace_admin_user_scopes_usecase import (
    ReplaceAdminUserScopesUsecase,
)
from src.application.admin.identity.user.reset_admin_user_password_usecase import (
    ResetAdminUserPasswordUsecase,
)
from src.application.admin.identity.user.update_admin_user_usecase import (
    UpdateAdminUserUsecase,
)
from src.application.admin.list_admin_log_records_usecase import (
    ListAdminLogRecordsUsecase,
)
from src.application.admin.list_admin_security_events_usecase import (
    ListAdminSecurityEventsUsecase,
)
from src.application.admin.list_admin_task_execution_records_usecase import (
    ListAdminTaskExecutionRecordsUsecase,
)
from src.application.admin.list_admin_task_registrations_usecase import (
    ListAdminTaskRegistrationsUsecase,
)
from src.application.admin.read_admin_task_runtime_usecase import (
    ReadAdminTaskRuntimeUsecase,
)
from src.application.admin.security_protection.manage_admin_security_ip_blocks_usecase import (
    CreateAdminSecurityIpBlockUsecase,
    GetAdminSecurityIpBlockUsecase,
    ListAdminSecurityIpBlocksUsecase,
    ReleaseAdminSecurityIpBlockUsecase,
)
from src.application.authorization_guard import AuthorizationGuard
from src.application.codex.execute_thread_command_usecase import (
    ExecuteCodexThreadCommandUsecase,
)
from src.application.codex.list_hosts_usecase import ListCodexHostsUsecase
from src.application.codex.list_workspaces_usecase import ListCodexWorkspacesUsecase
from src.application.codex.manage_approval_usecase import ManageCodexApprovalUsecase
from src.application.codex.query_threads_usecase import QueryCodexThreadsUsecase
from src.application.codex.read_thread_snapshot_usecase import (
    ReadCodexThreadSnapshotUsecase,
)
from src.application.codex.revoke_subject_agent_access_usecase import (
    RevokeCodexSubjectAgentAccessUsecase,
)
from src.application.codex.update_thread_preference_usecase import (
    UpdateCodexThreadPreferenceUsecase,
)
from src.application.codex.update_workspace_usecase import UpdateCodexWorkspaceUsecase
from src.application.health_probe_usecase import HealthProbeUsecase
from src.application.issue_access_token_usecase import IssueAccessTokenUsecase
from src.application.refresh_access_token_usecase import RefreshAccessTokenUsecase
from src.application.revoke_access_token_usecase import RevokeTokenSessionUsecase
from src.application.system_overview_usecase import SystemOverviewUsecase
from src.core.auth_contract.authenticated_principal_contract import AuthenticatedPrincipal
from src.core.auth_contract.authorization_policy_contract import (
    RouteAuthorizationRequirement,
)
from src.core.auth_contract.token_payload_contract import TokenPayload
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.http_contract.request_scope_contract import RequestScope
from src.core.http_contract.response_envelope_contract import ResponseEnvelopeFactory
from src.domain.auth.auth_error_code import AuthErrorCode
from src.infrastructure.request_execution_bridge import RequestExecutionBridge
from src.infrastructure.settings.settings_reload_coordinator import SettingsReloadCoordinator
from src.infrastructure.shared_resource_mount import SharedResourceMount

if TYPE_CHECKING:
    from src.api.fastapi_app_assembler import ApplicationContainer

MISSING_ACCESS_TOKEN_MESSAGE = "缺少访问令牌。"


@dataclass(slots=True, frozen=True)
class AuthRouteContext:
    """Authentication capability dependencies owned by the application root."""

    request_scope: RequestScope
    response_factory: ResponseEnvelopeFactory
    issue_access_token_usecase: IssueAccessTokenUsecase
    refresh_access_token_usecase: RefreshAccessTokenUsecase
    revoke_access_token_usecase: RevokeTokenSessionUsecase
    authorization_guard: AuthorizationGuard
    resource_mount: SharedResourceMount
    reload_coordinator: SettingsReloadCoordinator
    ready_probe_enabled: bool


@dataclass(slots=True, frozen=True)
class SystemRouteContext:
    """System and readiness capability dependencies."""

    health_probe_usecase: HealthProbeUsecase
    system_overview_usecase: SystemOverviewUsecase


@dataclass(slots=True, frozen=True)
class AdminRouteContext:
    """Administrative capability dependencies."""

    list_admin_task_execution_records_usecase: ListAdminTaskExecutionRecordsUsecase
    get_admin_task_execution_record_usecase: GetAdminTaskExecutionRecordUsecase
    read_admin_task_runtime_usecase: ReadAdminTaskRuntimeUsecase
    list_admin_task_registrations_usecase: ListAdminTaskRegistrationsUsecase
    dispatch_admin_task_usecase: DispatchAdminTaskUsecase
    build_admin_settings_reload_candidate_usecase: BuildAdminSettingsReloadCandidateUsecase
    apply_admin_settings_reload_usecase: ApplyAdminSettingsReloadUsecase
    list_admin_log_records_usecase: ListAdminLogRecordsUsecase
    list_admin_security_events_usecase: ListAdminSecurityEventsUsecase
    list_admin_security_ip_blocks_usecase: ListAdminSecurityIpBlocksUsecase
    create_admin_security_ip_block_usecase: CreateAdminSecurityIpBlockUsecase
    get_admin_security_ip_block_usecase: GetAdminSecurityIpBlockUsecase
    release_admin_security_ip_block_usecase: ReleaseAdminSecurityIpBlockUsecase
    list_admin_audit_events_usecase: ListAdminAuditEventsUsecase
    list_admin_scopes_usecase: ListAdminScopesUsecase
    get_admin_scope_usecase: GetAdminScopeUsecase
    create_admin_scope_usecase: CreateAdminScopeUsecase
    update_admin_scope_usecase: UpdateAdminScopeUsecase
    delete_admin_scope_usecase: DeleteAdminScopeUsecase
    list_admin_roles_usecase: ListAdminRolesUsecase
    get_admin_role_usecase: GetAdminRoleUsecase
    create_admin_role_usecase: CreateAdminRoleUsecase
    update_admin_role_usecase: UpdateAdminRoleUsecase
    replace_admin_role_scopes_usecase: ReplaceAdminRoleScopesUsecase
    delete_admin_role_usecase: DeleteAdminRoleUsecase
    list_admin_users_usecase: ListAdminUsersUsecase
    get_admin_user_usecase: GetAdminUserUsecase
    create_admin_user_usecase: CreateAdminUserUsecase
    update_admin_user_usecase: UpdateAdminUserUsecase
    reset_admin_user_password_usecase: ResetAdminUserPasswordUsecase
    replace_admin_user_roles_usecase: ReplaceAdminUserRolesUsecase
    replace_admin_user_scopes_usecase: ReplaceAdminUserScopesUsecase
    delete_admin_user_usecase: DeleteAdminUserUsecase


@dataclass(slots=True, frozen=True)
class CodexRouteContext:
    """Codex host, workspace and thread capability dependencies."""

    revoke_codex_subject_agent_access_usecase: RevokeCodexSubjectAgentAccessUsecase
    list_codex_hosts_usecase: ListCodexHostsUsecase
    list_codex_workspaces_usecase: ListCodexWorkspacesUsecase
    update_codex_workspace_usecase: UpdateCodexWorkspaceUsecase
    update_codex_thread_preference_usecase: UpdateCodexThreadPreferenceUsecase
    query_codex_threads_usecase: QueryCodexThreadsUsecase
    execute_codex_thread_command_usecase: ExecuteCodexThreadCommandUsecase
    read_codex_thread_snapshot_usecase: ReadCodexThreadSnapshotUsecase
    manage_codex_approval_usecase: ManageCodexApprovalUsecase


@dataclass(slots=True, frozen=True)
class StreamingRouteContext:
    """Streaming capability dependencies."""

    request_execution_bridge: RequestExecutionBridge
    resource_mount: SharedResourceMount
    authorization_guard: AuthorizationGuard


@dataclass(slots=True)
class RouteDependencyContext:
    """
    路由依赖上下文。
    """

    request_scope: RequestScope
    response_factory: ResponseEnvelopeFactory
    request_execution_bridge: RequestExecutionBridge
    health_probe_usecase: HealthProbeUsecase
    system_overview_usecase: SystemOverviewUsecase
    issue_access_token_usecase: IssueAccessTokenUsecase
    refresh_access_token_usecase: RefreshAccessTokenUsecase
    revoke_access_token_usecase: RevokeTokenSessionUsecase
    ready_probe_enabled: bool
    authorization_guard: AuthorizationGuard
    resource_mount: SharedResourceMount
    reload_coordinator: SettingsReloadCoordinator
    list_admin_task_execution_records_usecase: ListAdminTaskExecutionRecordsUsecase
    get_admin_task_execution_record_usecase: GetAdminTaskExecutionRecordUsecase
    read_admin_task_runtime_usecase: ReadAdminTaskRuntimeUsecase
    list_admin_task_registrations_usecase: ListAdminTaskRegistrationsUsecase
    dispatch_admin_task_usecase: DispatchAdminTaskUsecase
    build_admin_settings_reload_candidate_usecase: BuildAdminSettingsReloadCandidateUsecase
    apply_admin_settings_reload_usecase: ApplyAdminSettingsReloadUsecase
    list_admin_log_records_usecase: ListAdminLogRecordsUsecase
    list_admin_security_events_usecase: ListAdminSecurityEventsUsecase
    list_admin_security_ip_blocks_usecase: ListAdminSecurityIpBlocksUsecase
    create_admin_security_ip_block_usecase: CreateAdminSecurityIpBlockUsecase
    get_admin_security_ip_block_usecase: GetAdminSecurityIpBlockUsecase
    release_admin_security_ip_block_usecase: ReleaseAdminSecurityIpBlockUsecase
    list_admin_audit_events_usecase: ListAdminAuditEventsUsecase
    list_admin_scopes_usecase: ListAdminScopesUsecase
    get_admin_scope_usecase: GetAdminScopeUsecase
    create_admin_scope_usecase: CreateAdminScopeUsecase
    update_admin_scope_usecase: UpdateAdminScopeUsecase
    delete_admin_scope_usecase: DeleteAdminScopeUsecase
    list_admin_roles_usecase: ListAdminRolesUsecase
    get_admin_role_usecase: GetAdminRoleUsecase
    create_admin_role_usecase: CreateAdminRoleUsecase
    update_admin_role_usecase: UpdateAdminRoleUsecase
    replace_admin_role_scopes_usecase: ReplaceAdminRoleScopesUsecase
    delete_admin_role_usecase: DeleteAdminRoleUsecase
    list_admin_users_usecase: ListAdminUsersUsecase
    get_admin_user_usecase: GetAdminUserUsecase
    create_admin_user_usecase: CreateAdminUserUsecase
    update_admin_user_usecase: UpdateAdminUserUsecase
    reset_admin_user_password_usecase: ResetAdminUserPasswordUsecase
    replace_admin_user_roles_usecase: ReplaceAdminUserRolesUsecase
    replace_admin_user_scopes_usecase: ReplaceAdminUserScopesUsecase
    delete_admin_user_usecase: DeleteAdminUserUsecase
    revoke_codex_subject_agent_access_usecase: RevokeCodexSubjectAgentAccessUsecase
    list_codex_hosts_usecase: ListCodexHostsUsecase
    list_codex_workspaces_usecase: ListCodexWorkspacesUsecase
    update_codex_workspace_usecase: UpdateCodexWorkspaceUsecase
    update_codex_thread_preference_usecase: UpdateCodexThreadPreferenceUsecase
    query_codex_threads_usecase: QueryCodexThreadsUsecase
    execute_codex_thread_command_usecase: ExecuteCodexThreadCommandUsecase
    read_codex_thread_snapshot_usecase: ReadCodexThreadSnapshotUsecase
    manage_codex_approval_usecase: ManageCodexApprovalUsecase


class DependencyContextAccessor:
    """
    依赖上下文访问器，集中封装路由层直接需要的读取路径。
    """

    @staticmethod
    def _container(request: Request) -> ApplicationContainer:
        """Return the application-root container without copying dependencies."""

        return cast("ApplicationContainer", request.app.state.container)

    def read_auth_context(self, request: Request) -> AuthRouteContext:
        container = self._container(request)
        resource_mount = container.resource_mount
        runtime_settings = resource_mount.read_runtime_bundle().settings
        return AuthRouteContext(
            request_scope=request.state.request_scope,
            response_factory=container.response_factory,
            issue_access_token_usecase=container.issue_access_token_usecase,
            refresh_access_token_usecase=container.refresh_access_token_usecase,
            revoke_access_token_usecase=container.revoke_access_token_usecase,
            authorization_guard=resource_mount.get_authorization_guard(),
            resource_mount=resource_mount,
            reload_coordinator=container.reload_coordinator,
            ready_probe_enabled=runtime_settings.modules.system.ready_probe_enabled,
        )

    def read_system_context(self, request: Request) -> SystemRouteContext:
        container = self._container(request)
        return SystemRouteContext(
            health_probe_usecase=container.health_probe_usecase,
            system_overview_usecase=container.system_overview_usecase,
        )

    def read_admin_context(self, request: Request) -> AdminRouteContext:
        container = self._container(request)
        return AdminRouteContext(
            list_admin_task_execution_records_usecase=container.list_admin_task_execution_records_usecase,
            get_admin_task_execution_record_usecase=container.get_admin_task_execution_record_usecase,
            read_admin_task_runtime_usecase=container.read_admin_task_runtime_usecase,
            list_admin_task_registrations_usecase=container.list_admin_task_registrations_usecase,
            dispatch_admin_task_usecase=container.dispatch_admin_task_usecase,
            build_admin_settings_reload_candidate_usecase=container.build_admin_settings_reload_candidate_usecase,
            apply_admin_settings_reload_usecase=container.apply_admin_settings_reload_usecase,
            list_admin_log_records_usecase=container.list_admin_log_records_usecase,
            list_admin_security_events_usecase=container.list_admin_security_events_usecase,
            list_admin_security_ip_blocks_usecase=container.list_admin_security_ip_blocks_usecase,
            create_admin_security_ip_block_usecase=container.create_admin_security_ip_block_usecase,
            get_admin_security_ip_block_usecase=container.get_admin_security_ip_block_usecase,
            release_admin_security_ip_block_usecase=container.release_admin_security_ip_block_usecase,
            list_admin_audit_events_usecase=container.list_admin_audit_events_usecase,
            list_admin_scopes_usecase=container.list_admin_scopes_usecase,
            get_admin_scope_usecase=container.get_admin_scope_usecase,
            create_admin_scope_usecase=container.create_admin_scope_usecase,
            update_admin_scope_usecase=container.update_admin_scope_usecase,
            delete_admin_scope_usecase=container.delete_admin_scope_usecase,
            list_admin_roles_usecase=container.list_admin_roles_usecase,
            get_admin_role_usecase=container.get_admin_role_usecase,
            create_admin_role_usecase=container.create_admin_role_usecase,
            update_admin_role_usecase=container.update_admin_role_usecase,
            replace_admin_role_scopes_usecase=container.replace_admin_role_scopes_usecase,
            delete_admin_role_usecase=container.delete_admin_role_usecase,
            list_admin_users_usecase=container.list_admin_users_usecase,
            get_admin_user_usecase=container.get_admin_user_usecase,
            create_admin_user_usecase=container.create_admin_user_usecase,
            update_admin_user_usecase=container.update_admin_user_usecase,
            reset_admin_user_password_usecase=container.reset_admin_user_password_usecase,
            replace_admin_user_roles_usecase=container.replace_admin_user_roles_usecase,
            replace_admin_user_scopes_usecase=container.replace_admin_user_scopes_usecase,
            delete_admin_user_usecase=container.delete_admin_user_usecase,
        )

    def read_codex_context(self, request: Request) -> CodexRouteContext:
        container = self._container(request)
        return CodexRouteContext(
            revoke_codex_subject_agent_access_usecase=container.revoke_codex_subject_agent_access_usecase,
            list_codex_hosts_usecase=container.list_codex_hosts_usecase,
            list_codex_workspaces_usecase=container.list_codex_workspaces_usecase,
            update_codex_workspace_usecase=container.update_codex_workspace_usecase,
            update_codex_thread_preference_usecase=container.update_codex_thread_preference_usecase,
            query_codex_threads_usecase=container.query_codex_threads_usecase,
            execute_codex_thread_command_usecase=container.execute_codex_thread_command_usecase,
            read_codex_thread_snapshot_usecase=container.read_codex_thread_snapshot_usecase,
            manage_codex_approval_usecase=container.manage_codex_approval_usecase,
        )

    def read_streaming_context(self, request: Request) -> StreamingRouteContext:
        auth = self.read_auth_context(request)
        return StreamingRouteContext(
            request_execution_bridge=auth.resource_mount.get_request_execution_bridge(),
            resource_mount=auth.resource_mount,
            authorization_guard=auth.authorization_guard,
        )

    def read_route_context(self, request: Request) -> RouteDependencyContext:
        """
        读取当前路由上下文。
        """

        container = request.app.state.container
        resource_mount = container.resource_mount
        runtime_settings = resource_mount.read_runtime_bundle().settings
        return RouteDependencyContext(
            request_scope=request.state.request_scope,
            response_factory=container.response_factory,
            request_execution_bridge=resource_mount.get_request_execution_bridge(),
            health_probe_usecase=container.health_probe_usecase,
            system_overview_usecase=container.system_overview_usecase,
            issue_access_token_usecase=container.issue_access_token_usecase,
            refresh_access_token_usecase=container.refresh_access_token_usecase,
            revoke_access_token_usecase=container.revoke_access_token_usecase,
            ready_probe_enabled=runtime_settings.modules.system.ready_probe_enabled,
            authorization_guard=resource_mount.get_authorization_guard(),
            resource_mount=resource_mount,
            reload_coordinator=container.reload_coordinator,
            list_admin_task_execution_records_usecase=(
                container.list_admin_task_execution_records_usecase
            ),
            get_admin_task_execution_record_usecase=(
                container.get_admin_task_execution_record_usecase
            ),
            read_admin_task_runtime_usecase=container.read_admin_task_runtime_usecase,
            list_admin_task_registrations_usecase=(container.list_admin_task_registrations_usecase),
            dispatch_admin_task_usecase=container.dispatch_admin_task_usecase,
            build_admin_settings_reload_candidate_usecase=(
                container.build_admin_settings_reload_candidate_usecase
            ),
            apply_admin_settings_reload_usecase=(container.apply_admin_settings_reload_usecase),
            list_admin_log_records_usecase=container.list_admin_log_records_usecase,
            list_admin_security_events_usecase=(container.list_admin_security_events_usecase),
            list_admin_security_ip_blocks_usecase=(container.list_admin_security_ip_blocks_usecase),
            create_admin_security_ip_block_usecase=(
                container.create_admin_security_ip_block_usecase
            ),
            get_admin_security_ip_block_usecase=(container.get_admin_security_ip_block_usecase),
            release_admin_security_ip_block_usecase=(
                container.release_admin_security_ip_block_usecase
            ),
            list_admin_audit_events_usecase=(container.list_admin_audit_events_usecase),
            list_admin_scopes_usecase=container.list_admin_scopes_usecase,
            get_admin_scope_usecase=container.get_admin_scope_usecase,
            create_admin_scope_usecase=container.create_admin_scope_usecase,
            update_admin_scope_usecase=container.update_admin_scope_usecase,
            delete_admin_scope_usecase=container.delete_admin_scope_usecase,
            list_admin_roles_usecase=container.list_admin_roles_usecase,
            get_admin_role_usecase=container.get_admin_role_usecase,
            create_admin_role_usecase=container.create_admin_role_usecase,
            update_admin_role_usecase=container.update_admin_role_usecase,
            replace_admin_role_scopes_usecase=(container.replace_admin_role_scopes_usecase),
            delete_admin_role_usecase=container.delete_admin_role_usecase,
            list_admin_users_usecase=container.list_admin_users_usecase,
            get_admin_user_usecase=container.get_admin_user_usecase,
            create_admin_user_usecase=container.create_admin_user_usecase,
            update_admin_user_usecase=container.update_admin_user_usecase,
            reset_admin_user_password_usecase=(container.reset_admin_user_password_usecase),
            replace_admin_user_roles_usecase=(container.replace_admin_user_roles_usecase),
            replace_admin_user_scopes_usecase=(container.replace_admin_user_scopes_usecase),
            delete_admin_user_usecase=container.delete_admin_user_usecase,
            revoke_codex_subject_agent_access_usecase=(
                container.revoke_codex_subject_agent_access_usecase
            ),
            list_codex_hosts_usecase=container.list_codex_hosts_usecase,
            list_codex_workspaces_usecase=container.list_codex_workspaces_usecase,
            update_codex_workspace_usecase=container.update_codex_workspace_usecase,
            update_codex_thread_preference_usecase=(
                container.update_codex_thread_preference_usecase
            ),
            query_codex_threads_usecase=container.query_codex_threads_usecase,
            execute_codex_thread_command_usecase=(container.execute_codex_thread_command_usecase),
            read_codex_thread_snapshot_usecase=(container.read_codex_thread_snapshot_usecase),
            manage_codex_approval_usecase=container.manage_codex_approval_usecase,
        )

    def read_request_scope(self, request: Request) -> RequestScope:
        """
        读取请求作用域。
        """

        return request.state.request_scope

    def read_response_factory(self, request: Request) -> ResponseEnvelopeFactory:
        """
        读取响应工厂。
        """

        return self._container(request).response_factory

    def read_health_probe_usecase(self, request: Request) -> HealthProbeUsecase:
        """
        读取健康探针用例。
        """

        return self.read_system_context(request).health_probe_usecase

    def read_system_overview_usecase(
        self,
        request: Request,
    ) -> SystemOverviewUsecase:
        """
        读取系统概览用例。
        """

        return self.read_system_context(request).system_overview_usecase

    def read_issue_access_token_usecase(
        self,
        request: Request,
    ) -> IssueAccessTokenUsecase:
        """
        读取签发访问令牌用例。
        """

        return self.read_auth_context(request).issue_access_token_usecase

    def read_refresh_access_token_usecase(
        self,
        request: Request,
    ) -> RefreshAccessTokenUsecase:
        """
        读取刷新访问令牌用例。
        """

        return self.read_auth_context(request).refresh_access_token_usecase

    def read_revoke_access_token_usecase(
        self,
        request: Request,
    ) -> RevokeTokenSessionUsecase:
        """
        读取撤销访问令牌用例。
        """

        return self.read_auth_context(request).revoke_access_token_usecase

    def read_request_execution_bridge(
        self,
        request: Request,
    ) -> RequestExecutionBridge:
        """
        读取请求执行桥接器。
        """

        return self.read_streaming_context(request).request_execution_bridge

    def read_ready_probe_enabled(self, request: Request) -> bool:
        """
        读取严格就绪探针开关。
        """

        return self._container(request).resource_mount.read_health_snapshot().ready_probe_enabled

    def read_resource_mount(self, request: Request) -> SharedResourceMount:
        """
        读取共享资源挂载点。

        :param request: 当前 HTTP 请求对象。
        :type request: Request
        :returns: 共享资源挂载点。
        :rtype: SharedResourceMount
        """

        return self.read_auth_context(request).resource_mount

    def read_reload_coordinator(self, request: Request) -> SettingsReloadCoordinator:
        """
        读取配置热更新协调器。

        :param request: 当前 HTTP 请求对象。
        :type request: Request
        :returns: 配置热更新协调器。
        :rtype: SettingsReloadCoordinator
        """

        return self.read_auth_context(request).reload_coordinator

    def read_list_admin_task_execution_records_usecase(
        self,
        request: Request,
    ) -> ListAdminTaskExecutionRecordsUsecase:
        """
        读取管理员任务执行记录列表用例。

        :param request: 当前 HTTP 请求对象。
        :type request: Request
        :returns: 管理员任务执行记录列表用例。
        :rtype: ListAdminTaskExecutionRecordsUsecase
        """

        return self.read_admin_context(request).list_admin_task_execution_records_usecase

    def read_get_admin_task_execution_record_usecase(
        self,
        request: Request,
    ) -> GetAdminTaskExecutionRecordUsecase:
        """
        读取管理员任务执行记录详情用例。

        :param request: 当前 HTTP 请求对象。
        :type request: Request
        :returns: 管理员任务执行记录详情用例。
        :rtype: GetAdminTaskExecutionRecordUsecase
        """

        return self.read_admin_context(request).get_admin_task_execution_record_usecase

    def read_admin_task_runtime_usecase(
        self,
        request: Request,
    ) -> ReadAdminTaskRuntimeUsecase:
        """
        读取管理员任务运行时用例。

        :param request: 当前 HTTP 请求对象。
        :type request: Request
        :returns: 管理员任务运行时用例。
        :rtype: ReadAdminTaskRuntimeUsecase
        """

        return self.read_admin_context(request).read_admin_task_runtime_usecase

    def read_list_admin_task_registrations_usecase(
        self,
        request: Request,
    ) -> ListAdminTaskRegistrationsUsecase:
        """
        读取管理员任务注册列表用例。

        :param request: 当前 HTTP 请求对象。
        :type request: Request
        :returns: 管理员任务注册列表用例。
        :rtype: ListAdminTaskRegistrationsUsecase
        """

        return self.read_admin_context(request).list_admin_task_registrations_usecase

    def read_dispatch_admin_task_usecase(
        self,
        request: Request,
    ) -> DispatchAdminTaskUsecase:
        """
        读取管理员任务派发用例。

        :param request: 当前 HTTP 请求对象。
        :type request: Request
        :returns: 管理员任务派发用例。
        :rtype: DispatchAdminTaskUsecase
        """

        return self.read_admin_context(request).dispatch_admin_task_usecase

    def read_build_admin_settings_reload_candidate_usecase(
        self,
        request: Request,
    ) -> BuildAdminSettingsReloadCandidateUsecase:
        """
        读取管理员配置热更新候选用例。

        :param request: 当前 HTTP 请求对象。
        :type request: Request
        :returns: 管理员配置热更新候选用例。
        :rtype: BuildAdminSettingsReloadCandidateUsecase
        """

        return self.read_admin_context(request).build_admin_settings_reload_candidate_usecase

    def read_apply_admin_settings_reload_usecase(
        self,
        request: Request,
    ) -> ApplyAdminSettingsReloadUsecase:
        """
        读取管理员配置热更新执行用例。

        :param request: 当前 HTTP 请求对象。
        :type request: Request
        :returns: 管理员配置热更新执行用例。
        :rtype: ApplyAdminSettingsReloadUsecase
        """

        return self.read_admin_context(request).apply_admin_settings_reload_usecase

    def read_list_admin_log_records_usecase(
        self,
        request: Request,
    ) -> ListAdminLogRecordsUsecase:
        """
        读取管理员日志记录列表用例。

        :param request: 当前 HTTP 请求对象。
        :type request: Request
        :returns: 管理员日志记录列表用例。
        :rtype: ListAdminLogRecordsUsecase
        """

        return self.read_admin_context(request).list_admin_log_records_usecase

    def read_list_admin_security_events_usecase(
        self,
        request: Request,
    ) -> ListAdminSecurityEventsUsecase:
        """
        读取管理员安全事件列表用例。

        :param request: 当前 HTTP 请求对象。
        :type request: Request
        :returns: 管理员安全事件列表用例。
        :rtype: ListAdminSecurityEventsUsecase
        """

        return self.read_admin_context(request).list_admin_security_events_usecase

    def read_list_admin_security_ip_blocks_usecase(
        self,
        request: Request,
    ) -> ListAdminSecurityIpBlocksUsecase:
        """
        读取管理员安全 IP 封禁列表用例。
        """

        return self.read_admin_context(request).list_admin_security_ip_blocks_usecase

    def read_create_admin_security_ip_block_usecase(
        self,
        request: Request,
    ) -> CreateAdminSecurityIpBlockUsecase:
        """
        读取管理员安全 IP 封禁创建用例。
        """

        return self.read_admin_context(request).create_admin_security_ip_block_usecase

    def read_get_admin_security_ip_block_usecase(
        self,
        request: Request,
    ) -> GetAdminSecurityIpBlockUsecase:
        """
        读取管理员安全 IP 封禁详情用例。
        """

        return self.read_admin_context(request).get_admin_security_ip_block_usecase

    def read_release_admin_security_ip_block_usecase(
        self,
        request: Request,
    ) -> ReleaseAdminSecurityIpBlockUsecase:
        """
        读取管理员安全 IP 封禁释放用例。
        """

        return self.read_admin_context(request).release_admin_security_ip_block_usecase

    def read_list_admin_audit_events_usecase(
        self,
        request: Request,
    ) -> ListAdminAuditEventsUsecase:
        """
        读取业务审计事件列表用例。

        :param request: 当前 HTTP 请求对象。
        :type request: Request
        :returns: 业务审计事件列表用例。
        :rtype: ListAdminAuditEventsUsecase
        """

        return self.read_admin_context(request).list_admin_audit_events_usecase

    def read_list_admin_scopes_usecase(
        self,
        request: Request,
    ) -> ListAdminScopesUsecase:
        """
        读取管理员 scope 列表用例。
        """

        return self.read_admin_context(request).list_admin_scopes_usecase

    def read_get_admin_scope_usecase(self, request: Request) -> GetAdminScopeUsecase:
        """
        读取管理员 scope 详情用例。
        """

        return self.read_admin_context(request).get_admin_scope_usecase

    def read_create_admin_scope_usecase(
        self,
        request: Request,
    ) -> CreateAdminScopeUsecase:
        """
        读取管理员 scope 创建用例。
        """

        return self.read_admin_context(request).create_admin_scope_usecase

    def read_update_admin_scope_usecase(
        self,
        request: Request,
    ) -> UpdateAdminScopeUsecase:
        """
        读取管理员 scope 更新用例。
        """

        return self.read_admin_context(request).update_admin_scope_usecase

    def read_delete_admin_scope_usecase(
        self,
        request: Request,
    ) -> DeleteAdminScopeUsecase:
        """
        读取管理员 scope 删除用例。
        """

        return self.read_admin_context(request).delete_admin_scope_usecase

    def read_list_admin_roles_usecase(
        self,
        request: Request,
    ) -> ListAdminRolesUsecase:
        """
        读取管理员角色列表用例。
        """

        return self.read_admin_context(request).list_admin_roles_usecase

    def read_get_admin_role_usecase(self, request: Request) -> GetAdminRoleUsecase:
        """
        读取管理员角色详情用例。
        """

        return self.read_admin_context(request).get_admin_role_usecase

    def read_create_admin_role_usecase(
        self,
        request: Request,
    ) -> CreateAdminRoleUsecase:
        """
        读取管理员角色创建用例。
        """

        return self.read_admin_context(request).create_admin_role_usecase

    def read_update_admin_role_usecase(
        self,
        request: Request,
    ) -> UpdateAdminRoleUsecase:
        """
        读取管理员角色更新用例。
        """

        return self.read_admin_context(request).update_admin_role_usecase

    def read_replace_admin_role_scopes_usecase(
        self,
        request: Request,
    ) -> ReplaceAdminRoleScopesUsecase:
        """
        读取管理员角色 scope 替换用例。
        """

        return self.read_admin_context(request).replace_admin_role_scopes_usecase

    def read_delete_admin_role_usecase(
        self,
        request: Request,
    ) -> DeleteAdminRoleUsecase:
        """
        读取管理员角色删除用例。
        """

        return self.read_admin_context(request).delete_admin_role_usecase

    def read_list_admin_users_usecase(
        self,
        request: Request,
    ) -> ListAdminUsersUsecase:
        """
        读取管理员用户列表用例。
        """

        return self.read_admin_context(request).list_admin_users_usecase

    def read_get_admin_user_usecase(self, request: Request) -> GetAdminUserUsecase:
        """
        读取管理员用户详情用例。
        """

        return self.read_admin_context(request).get_admin_user_usecase

    def read_create_admin_user_usecase(
        self,
        request: Request,
    ) -> CreateAdminUserUsecase:
        """
        读取管理员用户创建用例。
        """

        return self.read_admin_context(request).create_admin_user_usecase

    def read_update_admin_user_usecase(
        self,
        request: Request,
    ) -> UpdateAdminUserUsecase:
        """
        读取管理员用户更新用例。
        """

        return self.read_admin_context(request).update_admin_user_usecase

    def read_reset_admin_user_password_usecase(
        self,
        request: Request,
    ) -> ResetAdminUserPasswordUsecase:
        """
        读取管理员用户密码重置用例。
        """

        return self.read_admin_context(request).reset_admin_user_password_usecase

    def read_replace_admin_user_roles_usecase(
        self,
        request: Request,
    ) -> ReplaceAdminUserRolesUsecase:
        """
        读取管理员用户角色替换用例。
        """

        return self.read_admin_context(request).replace_admin_user_roles_usecase

    def read_replace_admin_user_scopes_usecase(
        self,
        request: Request,
    ) -> ReplaceAdminUserScopesUsecase:
        """读取管理员用户直接 scope 替换用例。"""

        return self.read_admin_context(request).replace_admin_user_scopes_usecase

    def read_delete_admin_user_usecase(
        self,
        request: Request,
    ) -> DeleteAdminUserUsecase:
        """
        读取管理员用户删除用例。
        """

        return self.read_admin_context(request).delete_admin_user_usecase

    def read_revoke_codex_subject_agent_access_usecase(
        self,
        request: Request,
    ) -> RevokeCodexSubjectAgentAccessUsecase:
        """读取按主体撤销 Codex Agent 在线访问用例。"""

        return self.read_codex_context(request).revoke_codex_subject_agent_access_usecase

    def read_list_codex_hosts_usecase(self, request: Request) -> ListCodexHostsUsecase:
        """读取 Codex 主机列表用例。"""

        return self.read_codex_context(request).list_codex_hosts_usecase

    def read_list_codex_workspaces_usecase(
        self,
        request: Request,
    ) -> ListCodexWorkspacesUsecase:
        """读取 Codex 工作区列表用例。"""

        return self.read_codex_context(request).list_codex_workspaces_usecase

    def read_update_codex_workspace_usecase(
        self,
        request: Request,
    ) -> UpdateCodexWorkspaceUsecase:
        """读取 Codex 工作区更新用例。"""

        return self.read_codex_context(request).update_codex_workspace_usecase

    def read_query_codex_threads_usecase(self, request: Request) -> QueryCodexThreadsUsecase:
        """读取 Codex 线程索引查询用例。"""

        return self.read_codex_context(request).query_codex_threads_usecase

    def read_update_codex_thread_preference_usecase(
        self,
        request: Request,
    ) -> UpdateCodexThreadPreferenceUsecase:
        """读取 Codex 会话置顶偏好更新用例。"""

        return self.read_codex_context(request).update_codex_thread_preference_usecase

    def read_execute_codex_thread_command_usecase(
        self,
        request: Request,
    ) -> ExecuteCodexThreadCommandUsecase:
        """读取 Codex thread/turn 命令受理用例。"""

        return self.read_codex_context(request).execute_codex_thread_command_usecase

    def read_codex_thread_snapshot_usecase(
        self,
        request: Request,
    ) -> ReadCodexThreadSnapshotUsecase:
        """读取 Codex thread 权威 snapshot 用例。"""

        return self.read_codex_context(request).read_codex_thread_snapshot_usecase

    def read_manage_codex_approval_usecase(
        self,
        request: Request,
    ) -> ManageCodexApprovalUsecase:
        """读取 Codex 审批状态机用例。"""

        return self.read_codex_context(request).manage_codex_approval_usecase

    def read_authenticated_principal(self, request: Request) -> AuthenticatedPrincipal:
        """
        读取已认证主体。
        """

        auth_fault = getattr(request.state, "auth_fault", None)
        if auth_fault is not None:
            raise auth_fault
        principal = getattr(request.state, "authenticated_principal", None)
        if not isinstance(principal, AuthenticatedPrincipal):
            raise HttpFaultException(
                status_code=HTTPStatus.UNAUTHORIZED,
                error_code=AuthErrorCode.TOKEN_INVALID,
                message=MISSING_ACCESS_TOKEN_MESSAGE,
            )
        return principal

    def read_access_token_payload(self, request: Request) -> TokenPayload:
        """读取已验证的访问令牌载荷。"""

        self.read_authenticated_principal(request)
        payload = getattr(request.state, "access_token_payload", None)
        if not isinstance(payload, TokenPayload):
            raise HttpFaultException(
                status_code=HTTPStatus.UNAUTHORIZED,
                error_code=AuthErrorCode.TOKEN_INVALID,
                message=MISSING_ACCESS_TOKEN_MESSAGE,
            )
        return payload

    def read_authorized_principal(
        self,
        request: Request,
        requirement: RouteAuthorizationRequirement,
    ) -> AuthenticatedPrincipal:
        """
        读取已授权主体。
        """

        principal = self.read_authenticated_principal(request)
        try:
            self.read_auth_context(request).authorization_guard.assert_requirement(
                principal=principal,
                requirement=requirement,
            )
        except HttpFaultException as exc:
            resource_mount = request.app.state.container.resource_mount
            resource_mount.emit_security_event(
                resource_mount.get_security_event_builder().build_authorization_denied_event(
                    request=request,
                    subject_id=principal.subject_id,
                    reason_code=str(exc.error_code),
                    status_code=exc.status_code,
                )
            )
            raise
        return principal
