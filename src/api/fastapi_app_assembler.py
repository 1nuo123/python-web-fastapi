"""
FastAPI 应用组合根。

组合根负责连接 API 适配器、应用用例与基础设施实现，因此归属于最外层 API
包，不作为可被核心层依赖的基础设施组件。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI

from src.api.admin_task_stream_binding_factory import AdminTaskStreamBindingFactory
from src.api.fastapi_stream_route_composer import FastApiStreamRouteComposer
from src.api.task_binding_provider import ApplicationTaskBindingProvider
from src.api.web_bundle_catalog import WebBundleCatalog
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
from src.application.dispatch_background_job_usecase import DispatchBackgroundJobUsecase
from src.application.health_probe_usecase import HealthProbeUsecase
from src.application.issue_access_token_usecase import IssueAccessTokenUsecase
from src.application.refresh_access_token_usecase import RefreshAccessTokenUsecase
from src.application.revoke_access_token_usecase import RevokeTokenSessionUsecase
from src.application.system_overview_usecase import SystemOverviewUsecase
from src.core.http_contract.response_envelope_contract import ResponseEnvelopeFactory
from src.core.http_contract.web_bundle_contract import ApplicationModuleName
from src.infrastructure.admin_settings_reload_adapter import AdminSettingsReloadAdapter
from src.infrastructure.fastapi_exception_presenter import FastApiExceptionPresenter
from src.infrastructure.fastapi_lifespan_orchestrator import FastApiLifespanOrchestrator
from src.infrastructure.fastapi_middleware_plan import FastApiMiddlewarePlan
from src.infrastructure.fastapi_openapi_surface import FastApiOpenApiSurface
from src.infrastructure.fastapi_otel_bridge import FastApiOtelBridge
from src.infrastructure.fastapi_route_composer import FastApiRouteComposer
from src.infrastructure.logging.app_logger_factory import AppLoggerFactory
from src.infrastructure.observability.prometheus_metrics_registry import (
    PrometheusMetricsRegistry,
    PrometheusMetricsRegistryOptions,
)
from src.infrastructure.observability.prometheus_metrics_route import (
    PrometheusHttpMetricsMiddleware,
    PrometheusMetricsRoute,
)
from src.infrastructure.orjson_document_response import OrjsonDocumentResponse
from src.infrastructure.persistence.database_engine_factory_contract import (
    DatabaseEngineFactory,
)
from src.infrastructure.settings.app_settings_loader import (
    AppSettingsLoader,
)
from src.infrastructure.settings.application_settings import (
    AppEnvironment,
    ApplicationSettings,
)
from src.infrastructure.settings.raw_application_settings import SettingsOverrideMapping
from src.infrastructure.settings.settings_reload_coordinator import SettingsReloadCoordinator
from src.infrastructure.settings.settings_snapshot_store import (
    SettingsSnapshotStore,
    SettingsStateHolder,
)
from src.infrastructure.shared_resource_mount import SharedResourceMount
from src.infrastructure.task.task_registration_registry import (
    BaseModelTaskBinding,
    TaskRegistrationRegistry,
)


@dataclass(frozen=True, slots=True)
class TaskBindingSource:
    """
    任务绑定来源。

    :ivar bindings: 已解析的任务绑定集合。
    :vartype bindings: list[RegisteredTaskBinding]
    :ivar strict: 是否按显式绑定严格校验未声明任务。
    :vartype strict: bool
    """

    bindings: list[BaseModelTaskBinding]
    strict: bool


@dataclass(slots=True)
class ApplicationContainer:
    """
    应用容器数据对象，用于承载当前流程的结构化字段。

    :ivar settings_holder: 当前生效配置持有器。约束：需符合 ``SettingsStateHolder`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype settings_holder: SettingsStateHolder
    :ivar response_factory: ``response_factory`` 字段。约束：需符合 ``ResponseEnvelopeFactory`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype response_factory: ResponseEnvelopeFactory
    :ivar resource_mount: 共享资源挂载点。约束：需符合 ``SharedResourceMount`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype resource_mount: SharedResourceMount
    :ivar health_probe_usecase: ``health_probe_usecase`` 字段。约束：需符合 ``HealthProbeUsecase`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype health_probe_usecase: HealthProbeUsecase
    :ivar system_overview_usecase: ``system_overview_usecase`` 字段。约束：需符合 ``SystemOverviewUsecase`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype system_overview_usecase: SystemOverviewUsecase
    :ivar issue_access_token_usecase: ``issue_access_token_usecase`` 字段。约束：需符合 ``IssueAccessTokenUsecase`` 注解。默认值：无，必须显式提供。取值语义：用于表达访问令牌、刷新令牌或令牌会话信息。
    :vartype issue_access_token_usecase: IssueAccessTokenUsecase
    :ivar refresh_access_token_usecase: ``refresh_access_token_usecase`` 字段。约束：需符合 ``RefreshAccessTokenUsecase`` 注解。默认值：无，必须显式提供。取值语义：用于表达访问令牌、刷新令牌或令牌会话信息。
    :vartype refresh_access_token_usecase: RefreshAccessTokenUsecase
    :ivar revoke_access_token_usecase: ``revoke_access_token_usecase`` 字段。约束：需符合 ``RevokeTokenSessionUsecase`` 注解。默认值：无，必须显式提供。取值语义：用于撤销令牌会话。
    :vartype revoke_access_token_usecase: RevokeTokenSessionUsecase
    :ivar dispatch_background_job_usecase: ``dispatch_background_job_usecase`` 字段。约束：需符合 ``DispatchBackgroundJobUsecase`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype dispatch_background_job_usecase: DispatchBackgroundJobUsecase
    :ivar reload_coordinator: ``reload_coordinator`` 字段。约束：需符合 ``SettingsReloadCoordinator`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype reload_coordinator: SettingsReloadCoordinator
    """

    settings_holder: SettingsStateHolder
    response_factory: ResponseEnvelopeFactory
    resource_mount: SharedResourceMount
    stream_route_composer: FastApiStreamRouteComposer
    health_probe_usecase: HealthProbeUsecase
    system_overview_usecase: SystemOverviewUsecase
    issue_access_token_usecase: IssueAccessTokenUsecase
    refresh_access_token_usecase: RefreshAccessTokenUsecase
    revoke_access_token_usecase: RevokeTokenSessionUsecase
    dispatch_background_job_usecase: DispatchBackgroundJobUsecase
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
    delete_admin_user_usecase: DeleteAdminUserUsecase


class FastApiAppAssembler:
    """
    FastAPI应用装配器类型，用于封装当前模块中的相关行为或状态。
    """

    def __call__(
        self,
        *,
        environment: AppEnvironment | None = None,
        config_root: str | Path = "config",
        settings_overrides: SettingsOverrideMapping | None = None,
        task_bindings: list[BaseModelTaskBinding] | None = None,
        task_binding_provider: ApplicationTaskBindingProvider | None = None,
        database_engine_factory: DatabaseEngineFactory | None = None,
    ) -> FastAPI:
        """
        执行当前可调用对象。

        :param environment: 目标运行环境，用于选择配置文件层级。默认值：`None`。约束：需符合 ``AppEnvironment | None`` 注解。
        :type environment: AppEnvironment | None
        :param config_root: 配置根目录路径。默认值：`'config'`。约束：需符合 ``str | Path`` 注解。
        :type config_root: str | Path
        :param settings_overrides: 当前步骤使用的配置覆盖配置参数。默认值：`None`。约束：需符合 ``SettingsOverrideMapping | None`` 注解。
        :type settings_overrides: SettingsOverrideMapping | None
        :returns: 返回当前操作结果。
        :rtype: FastAPI
        :raises ValueError: 当输入值或配置值不满足当前实现约束时抛出。
        """

        settings_loader = AppSettingsLoader(config_root)
        settings = self._load_settings(
            settings_loader=settings_loader,
            environment=environment,
            settings_overrides=settings_overrides,
        )
        web_bundle_catalog = self._build_web_bundle_catalog()
        web_bundle_catalog.validate_enabled_modules(settings.app.modules.enabled)
        logger_factory = AppLoggerFactory()
        logger = logger_factory.build(settings)
        settings_holder = SettingsStateHolder(current_settings=settings)
        telemetry_bridge = FastApiOtelBridge(settings.runtime.otel)
        resource_mount = self._build_resource_mount(
            settings_holder=settings_holder,
            logger=logger,
            logger_factory=logger_factory,
            telemetry_bridge=telemetry_bridge,
            task_bindings=task_bindings,
            task_binding_provider=task_binding_provider,
            database_engine_factory=database_engine_factory,
        )
        reload_coordinator = self._build_reload_coordinator(
            settings_loader=settings_loader,
            settings_holder=settings_holder,
            logger_factory=logger_factory,
            logger=logger,
            resource_mount=resource_mount,
            settings_overrides=settings_overrides,
        )
        container = self._build_application_container(
            settings_holder=settings_holder,
            resource_mount=resource_mount,
            reload_coordinator=reload_coordinator,
        )
        app = self._build_fastapi_app(settings=settings, resource_mount=resource_mount)
        app.state.container = container
        app.state.ready = False
        telemetry_bridge.instrument_app(app)
        FastApiExceptionPresenter(
            resource_mount=resource_mount,
            logger=logger,
        ).bind(app)
        self._bind_middlewares(app=app, container=container, logger=logger)
        self._bind_prometheus_metrics(app=app, settings=settings, resource_mount=resource_mount)
        mounted_modules = FastApiRouteComposer().compose(
            app=app,
            bundles=web_bundle_catalog.build(),
            enabled_modules=settings.app.modules.enabled,
            api_prefix=settings.runtime.web.api_prefix,
        )
        resource_mount.set_enabled_web_modules(mounted_modules)
        if (
            settings.runtime.stream.header.enabled
            and ApplicationModuleName.ADMIN_TASK.value in mounted_modules
        ):
            container.stream_route_composer.compose(
                app=app,
                bindings=AdminTaskStreamBindingFactory().build(
                    settings=settings,
                    resource_mount=resource_mount,
                    response_factory=container.response_factory,
                ),
            )
        FastApiOpenApiSurface(app=app, resource_mount=resource_mount).bind()
        return app

    def _build_fastapi_app(
        self,
        *,
        settings: ApplicationSettings,
        resource_mount: SharedResourceMount,
    ) -> FastAPI:
        """
        构建 FastAPI 应用实例。

        :param settings: 已完成校验的应用配置。
        :type settings: ApplicationSettings
        :param resource_mount: 共享资源挂载点。
        :type resource_mount: SharedResourceMount
        :returns: 返回 FastAPI 应用实例。
        :rtype: FastAPI
        """

        return FastAPI(
            title=settings.app.name,
            version=settings.app.version,
            default_response_class=OrjsonDocumentResponse,
            lifespan=FastApiLifespanOrchestrator(resource_mount),
            openapi_url="/openapi.json" if settings.app.enable_openapi else None,
            docs_url="/docs" if settings.app.enable_openapi else None,
            redoc_url="/redoc" if settings.app.enable_openapi else None,
        )

    def _resolve_task_bindings(
        self,
        *,
        task_bindings: list[BaseModelTaskBinding] | None,
        task_binding_provider: ApplicationTaskBindingProvider | None,
    ) -> TaskBindingSource:
        """
        解析任务绑定集合。
        """

        if task_bindings is not None:
            return TaskBindingSource(bindings=list(task_bindings), strict=True)
        if task_binding_provider is None:
            return TaskBindingSource(bindings=[], strict=False)
        return TaskBindingSource(bindings=task_binding_provider.build(), strict=False)

    def _register_task_bindings(
        self,
        *,
        resource_mount: SharedResourceMount,
        registration_registry: TaskRegistrationRegistry,
        binding_source: TaskBindingSource,
    ) -> None:
        """
        注册任务绑定。
        """

        for binding in binding_source.bindings:
            if binding_source.strict:
                resource_mount.register_task_binding(binding)
                continue
            if not registration_registry.is_declared_job_kind(binding.job_kind):
                continue
            resource_mount.register_task_binding(binding)

    def _load_settings(
        self,
        *,
        settings_loader: AppSettingsLoader,
        environment: AppEnvironment | None,
        settings_overrides: SettingsOverrideMapping | None,
    ) -> ApplicationSettings:
        """
        加载应用配置。
        """

        if settings_overrides is not None:
            if environment is None:
                raise ValueError("使用 settings_overrides 时必须显式提供 environment。")
            return settings_loader.load_from_mapping(
                environment=environment,
                overrides=settings_overrides,
            )
        if environment is not None:
            return settings_loader.load_for_environment(environment)
        return settings_loader.load()

    def _build_resource_mount(
        self,
        *,
        settings_holder: SettingsStateHolder,
        logger: logging.Logger,
        logger_factory: AppLoggerFactory,
        telemetry_bridge: FastApiOtelBridge,
        task_bindings: list[BaseModelTaskBinding] | None,
        task_binding_provider: ApplicationTaskBindingProvider | None,
        database_engine_factory: DatabaseEngineFactory | None,
    ) -> SharedResourceMount:
        """
        构建共享资源挂载点。
        """

        resource_mount = SharedResourceMount(
            settings_holder=settings_holder,
            logger=logger,
            logger_factory=logger_factory,
            telemetry_bridge=telemetry_bridge,
            database_engine_factory=database_engine_factory,
        )
        binding_source = self._resolve_task_bindings(
            task_bindings=task_bindings,
            task_binding_provider=task_binding_provider,
        )
        self._register_task_bindings(
            resource_mount=resource_mount,
            registration_registry=resource_mount.get_task_registration_registry(),
            binding_source=binding_source,
        )
        return resource_mount

    def _build_reload_coordinator(
        self,
        *,
        settings_loader: AppSettingsLoader,
        settings_holder: SettingsStateHolder,
        logger_factory: AppLoggerFactory,
        logger: logging.Logger,
        resource_mount: SharedResourceMount,
        settings_overrides: SettingsOverrideMapping | None,
    ) -> SettingsReloadCoordinator:
        """
        构建配置重载协调器。
        """

        snapshot_store = SettingsSnapshotStore()
        reload_coordinator = SettingsReloadCoordinator(
            settings_loader=settings_loader,
            settings_holder=settings_holder,
            snapshot_store=snapshot_store,
            logger_factory=logger_factory,
            logger=logger,
            on_settings_applied=resource_mount.apply_settings,
            baseline_overrides=settings_overrides,
        )
        reload_coordinator.initialize_snapshot()
        return reload_coordinator

    def _build_application_container(
        self,
        *,
        settings_holder: SettingsStateHolder,
        resource_mount: SharedResourceMount,
        reload_coordinator: SettingsReloadCoordinator,
    ) -> ApplicationContainer:
        """
        构建应用容器。
        """

        dispatch_background_job_usecase = DispatchBackgroundJobUsecase(
            task_runtime_port=resource_mount,
        )
        admin_settings_reload_adapter = AdminSettingsReloadAdapter(
            resource_mount=resource_mount,
            reload_coordinator=reload_coordinator,
        )
        return ApplicationContainer(
            settings_holder=settings_holder,
            response_factory=ResponseEnvelopeFactory(),
            resource_mount=resource_mount,
            stream_route_composer=FastApiStreamRouteComposer(),
            health_probe_usecase=HealthProbeUsecase(settings_reader_port=resource_mount),
            system_overview_usecase=SystemOverviewUsecase(
                settings_reader_port=resource_mount,
            ),
            issue_access_token_usecase=IssueAccessTokenUsecase(runtime_port=resource_mount),
            refresh_access_token_usecase=RefreshAccessTokenUsecase(
                runtime_port=resource_mount,
            ),
            revoke_access_token_usecase=RevokeTokenSessionUsecase(
                runtime_port=resource_mount,
            ),
            dispatch_background_job_usecase=dispatch_background_job_usecase,
            reload_coordinator=reload_coordinator,
            list_admin_task_execution_records_usecase=(
                ListAdminTaskExecutionRecordsUsecase(
                    task_runtime_port=resource_mount,
                )
            ),
            get_admin_task_execution_record_usecase=(
                GetAdminTaskExecutionRecordUsecase(
                    task_runtime_port=resource_mount,
                )
            ),
            read_admin_task_runtime_usecase=ReadAdminTaskRuntimeUsecase(
                task_runtime_port=resource_mount,
            ),
            list_admin_task_registrations_usecase=(
                ListAdminTaskRegistrationsUsecase(
                    task_runtime_port=resource_mount,
                )
            ),
            dispatch_admin_task_usecase=DispatchAdminTaskUsecase(
                task_runtime_port=resource_mount,
                dispatch_background_job_usecase=dispatch_background_job_usecase,
            ),
            build_admin_settings_reload_candidate_usecase=(
                BuildAdminSettingsReloadCandidateUsecase(
                    admin_settings_reload_port=admin_settings_reload_adapter,
                )
            ),
            apply_admin_settings_reload_usecase=ApplyAdminSettingsReloadUsecase(
                admin_settings_reload_port=admin_settings_reload_adapter,
            ),
            list_admin_log_records_usecase=ListAdminLogRecordsUsecase(
                admin_log_query_port=resource_mount,
            ),
            list_admin_security_events_usecase=ListAdminSecurityEventsUsecase(
                admin_log_query_port=resource_mount,
            ),
            list_admin_security_ip_blocks_usecase=(
                ListAdminSecurityIpBlocksUsecase(runtime_port=resource_mount)
            ),
            create_admin_security_ip_block_usecase=(
                CreateAdminSecurityIpBlockUsecase(runtime_port=resource_mount)
            ),
            get_admin_security_ip_block_usecase=(
                GetAdminSecurityIpBlockUsecase(runtime_port=resource_mount)
            ),
            release_admin_security_ip_block_usecase=(
                ReleaseAdminSecurityIpBlockUsecase(runtime_port=resource_mount)
            ),
            list_admin_audit_events_usecase=ListAdminAuditEventsUsecase(
                admin_audit_query_port=resource_mount,
            ),
            list_admin_scopes_usecase=ListAdminScopesUsecase(
                admin_identity_port=resource_mount,
            ),
            get_admin_scope_usecase=GetAdminScopeUsecase(
                admin_identity_port=resource_mount,
            ),
            create_admin_scope_usecase=CreateAdminScopeUsecase(
                admin_identity_port=resource_mount,
            ),
            update_admin_scope_usecase=UpdateAdminScopeUsecase(
                admin_identity_port=resource_mount,
            ),
            delete_admin_scope_usecase=DeleteAdminScopeUsecase(
                admin_identity_port=resource_mount,
            ),
            list_admin_roles_usecase=ListAdminRolesUsecase(
                admin_identity_port=resource_mount,
            ),
            get_admin_role_usecase=GetAdminRoleUsecase(
                admin_identity_port=resource_mount,
            ),
            create_admin_role_usecase=CreateAdminRoleUsecase(
                admin_identity_port=resource_mount,
            ),
            update_admin_role_usecase=UpdateAdminRoleUsecase(
                admin_identity_port=resource_mount,
            ),
            replace_admin_role_scopes_usecase=ReplaceAdminRoleScopesUsecase(
                admin_identity_port=resource_mount,
            ),
            delete_admin_role_usecase=DeleteAdminRoleUsecase(
                admin_identity_port=resource_mount,
            ),
            list_admin_users_usecase=ListAdminUsersUsecase(
                admin_identity_port=resource_mount,
            ),
            get_admin_user_usecase=GetAdminUserUsecase(
                admin_identity_port=resource_mount,
            ),
            create_admin_user_usecase=CreateAdminUserUsecase(
                admin_identity_port=resource_mount,
            ),
            update_admin_user_usecase=UpdateAdminUserUsecase(
                admin_identity_port=resource_mount,
            ),
            reset_admin_user_password_usecase=ResetAdminUserPasswordUsecase(
                admin_identity_port=resource_mount,
            ),
            replace_admin_user_roles_usecase=ReplaceAdminUserRolesUsecase(
                admin_identity_port=resource_mount,
            ),
            delete_admin_user_usecase=DeleteAdminUserUsecase(
                admin_identity_port=resource_mount,
            ),
        )

    def _build_web_bundle_catalog(self) -> WebBundleCatalog:
        """
        构建 Web 模块目录。
        """

        return WebBundleCatalog()

    def _bind_prometheus_metrics(
        self,
        *,
        app: FastAPI,
        settings: ApplicationSettings,
        resource_mount: SharedResourceMount,
    ) -> None:
        """
        按运行时配置绑定 Prometheus 指标出口。

        指标注册器同时挂载到共享资源挂载点，供日志缓冲、任务执行链与
        饱和度刷新在启动阶段读取。

        :param app: 当前 FastAPI 应用。
        :type app: FastAPI
        :param settings: 已完成校验的应用配置。
        :type settings: ApplicationSettings
        :param resource_mount: 共享资源挂载点。
        :type resource_mount: SharedResourceMount
        :returns: 无返回值。
        :rtype: None
        """

        metrics_settings = settings.runtime.metrics
        if not metrics_settings.header.enabled:
            return
        registry = PrometheusMetricsRegistry(
            options=PrometheusMetricsRegistryOptions(
                include_security_metrics=metrics_settings.detail.include_security_metrics,
                include_task_metrics=metrics_settings.detail.include_task_metrics,
                include_log_buffer_metrics=metrics_settings.detail.include_log_buffer_metrics,
                include_saturation_metrics=metrics_settings.detail.include_saturation_metrics,
            )
        )
        resource_mount.install_metrics_registry(registry)
        if metrics_settings.detail.include_http_metrics:
            app.add_middleware(PrometheusHttpMetricsMiddleware, registry=registry)
        PrometheusMetricsRoute(
            registry=registry,
            metrics_path=metrics_settings.detail.metrics_path,
            include_runtime_metrics=metrics_settings.detail.include_runtime_metrics,
            saturation_probe=(
                resource_mount if metrics_settings.detail.include_saturation_metrics else None
            ),
        ).bind(app)

    def _bind_middlewares(
        self,
        *,
        app: FastAPI,
        container: ApplicationContainer,
        logger: logging.Logger,
    ) -> None:
        """
        绑定中间件集合。

        :param app: 当前 FastAPI 或 ASGI 应用实例。约束：需符合 ``FastAPI`` 注解。
        :type app: FastAPI
        :param container: 应用容器对象。约束：需符合 ``ApplicationContainer`` 注解。
        :type container: ApplicationContainer
        :param logger: 当前组件使用的日志记录器。
        :type logger: logging.Logger
        :returns: 无返回值。
        :rtype: None
        """

        middleware_plan = FastApiMiddlewarePlan()
        bindings = middleware_plan.build_bindings(
            resource_mount=container.resource_mount,
            logger=logger,
        )
        app.user_middleware = [*bindings, *app.user_middleware]
