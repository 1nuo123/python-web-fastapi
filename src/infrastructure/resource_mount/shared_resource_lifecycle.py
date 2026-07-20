"""共享资源生命周期管理。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

import hashlib
import logging
import threading
from http import HTTPStatus

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from src.application.authorization_guard import AuthorizationGuard
from src.application.ports.settings_reader_port import ApplicationSettingsSnapshot
from src.core.cache_contract.cache_store_contract import CacheStore
from src.core.exception_contract.error_code_catalog_contract import CoreErrorCode
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.http_contract.runtime_resource_contract import (
    RuntimeResourceState,
    RuntimeResourceStatus,
)
from src.core.http_contract.security_runtime_contract import IpBlockRuntimeDetail
from src.core.logging_contract.log_event_contract import (
    LogEventEnvelope,
    ResourceLifecycleAction,
)
from src.core.logging_contract.log_writer_contract import LogWriteReason
from src.core.persistence_contract.refresh_token_repository_contract import RefreshTokenRepository
from src.core.persistence_contract.unit_of_work_contract import PersistenceSession
from src.core.security_contract.security_event_contract import SecurityEventEnvelope
from src.core.task_contract.message_bus_contract import (
    MessageBus,
)
from src.domain.auth.access_token_policy import AccessTokenPolicy
from src.domain.auth.authorization_policy_evaluator import (
    AuthorizationPolicyEvaluator,
)
from src.infrastructure.auth.auth_failure_throttle import AuthFailureThrottle
from src.infrastructure.auth.bootstrap_admin_synchronizer import (
    BootstrapAdminSynchronizer,
)
from src.infrastructure.auth.jwt_token_service import JwtTokenService
from src.infrastructure.auth.oauth2_scheme_provider import OAuth2SchemeProvider
from src.infrastructure.auth.password_hasher import PasswordHasher
from src.infrastructure.cache.cache_key_builder import CacheKeyBuilder
from src.infrastructure.cache.cache_service import CacheService
from src.infrastructure.concurrency.distributed_lock_provider import (
    DistributedLockProvider,
)
from src.infrastructure.context.request_context_manager_impl import (
    RequestContextManagerImpl,
)
from src.infrastructure.fastapi_otel_bridge import FastApiOtelBridge
from src.infrastructure.key_management.database_key_ring_store import DatabaseKeyRingStore
from src.infrastructure.key_management.key_management_service import KeyManagementService
from src.infrastructure.key_management.key_rotation_service import KeyRotationService
from src.infrastructure.key_management.sensitive_digest_service import (
    SensitiveDigestService,
)
from src.infrastructure.logging.app_logger_factory import AppLoggerFactory
from src.infrastructure.logging.database_log_writer import DatabaseLogWriter
from src.infrastructure.logging.log_buffer_dispatcher import LogBufferDispatcher
from src.infrastructure.logging.log_event_builder import LogEventBuilder
from src.infrastructure.logging.structured_log_handler import StructuredLogHandler
from src.infrastructure.persistence.alembic_runner import AlembicRunner
from src.infrastructure.persistence.database_engine_factory_contract import (
    DatabaseEngineFactory,
)
from src.infrastructure.persistence.repository_impl.admin_identity_repository_impl import (
    AdminIdentityRepositoryImpl,
)
from src.infrastructure.persistence.repository_impl.security_ip_block_repository import (
    SecurityIpBlockRepository,
)
from src.infrastructure.persistence.sqlalchemy_engine_factory import (
    SqlAlchemyEngineFactory,
)
from src.infrastructure.persistence.sqlalchemy_session_factory import (
    SqlAlchemySessionFactory,
    SqlAlchemyUnitOfWork,
)
from src.infrastructure.resource_mount.runtime_accessor_refresher import (
    RuntimeAccessorRefresher,
)
from src.infrastructure.resource_mount.runtime_resource_bootstrapper import (
    RuntimeResourceBootstrapper,
)
from src.infrastructure.resource_mount.runtime_resource_mount_contract import (
    CACHE_RUNTIME_ATTACHED_KIND,
    DATABASE_RUNTIME_ATTACHED_KIND,
    HTTP_RUNTIME_ATTACHED_KIND,
    LOGGING_RUNTIME_ATTACHED_KIND,
    RUNTIME_ACCESSORS_REFRESHED_KIND,
    RUNTIME_RESOURCE_STATE_CHANGED_KIND,
    TASK_RUNTIME_ATTACHED_KIND,
    CacheRuntimeAttachedDetail,
    DatabaseRuntimeAttachedDetail,
    HttpRuntimeAttachedDetail,
    LoggingRuntimeAttachedDetail,
    RuntimeAccessorsRefreshedDetail,
    RuntimeResourceMountOperationDetail,
    RuntimeResourceMountOperationEnvelope,
    RuntimeResourceMountOperationHeader,
    RuntimeResourceStateChangedDetail,
    TaskRuntimeAttachedDetail,
)
from src.infrastructure.resource_mount.runtime_resource_releaser import (
    RuntimeResourceReleaseEnvelope,
    RuntimeResourceReleaser,
)
from src.infrastructure.resource_mount.shared_resource_constants import (
    ATTACH_HTTP_RUNTIME_OPERATION_NAME,
    CACHE_STORE_NOT_READY_MESSAGE,
    INSTALL_CACHE_RUNTIME_OPERATION_NAME,
    INSTALL_DATABASE_RUNTIME_OPERATION_NAME,
    INSTALL_LOGGING_RUNTIME_OPERATION_NAME,
    INSTALL_TASK_RUNTIME_OPERATION_NAME,
    MARK_RUNTIME_RESOURCE_STATE_OPERATION_NAME,
    PRODUCTION_BOOTSTRAP_ADMIN_BLOCKED_MESSAGE,
    REFRESH_RUNTIME_ACCESSORS_OPERATION_NAME,
    RESOURCE_ASYNC_HTTP_CLIENT,
    RESOURCE_CACHE,
    RESOURCE_DATABASE,
    RESOURCE_DISTRIBUTED_LOCK,
    RESOURCE_HTTP_CLIENT,
    RESOURCE_KEY_MANAGEMENT,
    RESOURCE_LOGGING,
    RESOURCE_RELEASE_BEGIN_MESSAGE,
    RESOURCE_RELEASE_FINISH_MESSAGE,
    RESOURCE_SECURITY_PROTECTION,
    RESOURCE_STARTUP_BEGIN_MESSAGE,
    RESOURCE_STARTUP_FAILED_MESSAGE,
    RESOURCE_STARTUP_FINISH_MESSAGE,
    RESOURCE_TASK,
    RESOURCE_TASK_MESSAGE_TRANSPORT,
    SETTINGS_APPLY_OPERATION_NAME,
    SETTINGS_APPLY_TARGET_RESOURCE,
    TASK_RESOURCE_READY_DETAIL,
)
from src.infrastructure.resource_mount.shared_resource_models import (
    AuthSupportAccessor,
    HttpRuntimeAccessor,
    LoggingSupportAccessor,
    RetiredRuntimeResources,
    RuntimeBundle,
    RuntimeDependencySet,
    TaskRuntimeAccessor,
    TaskRuntimeSet,
)
from src.infrastructure.resource_slot.shared_db_session_manager import (
    SharedDbSessionManager,
)
from src.infrastructure.resource_slot.shared_http_resource_manager import (
    SharedHttpResourceManager,
    SharedHttpResourceSet,
)
from src.infrastructure.security.client_ip_resolver import (
    ClientIpResolver,
    TrustedProxyPolicy,
)
from src.infrastructure.security.ip_block_guard import IpBlockGuard
from src.infrastructure.security.outbound_url_safety_httpx_hook import (
    AsyncOutboundUrlSafetyHook,
    SyncOutboundUrlSafetyHook,
)
from src.infrastructure.security.outbound_url_safety_validator import (
    OutboundUrlSafetyValidator,
)
from src.infrastructure.security.rate_limit_guard import RateLimitGuard
from src.infrastructure.security.risk_signal_guard import RiskSignalGuard
from src.infrastructure.security.security_event_builder import SecurityEventBuilder
from src.infrastructure.security.security_protection_guard import SecurityProtectionGuard
from src.infrastructure.security.token_binding_guard import TokenBindingGuard
from src.infrastructure.settings.application_settings import (
    AppEnvironment,
    ApplicationSettings,
    DatabaseRuntimeSettings,
)
from src.infrastructure.settings.runtime_capacity_policy_resolver import (
    RuntimeCapacityPolicyResolver,
)
from src.infrastructure.settings.settings_apply_contract import (
    HTTP_RESOURCE_SWITCH_DETAIL_KIND,
    TASK_REGISTRY_RELOAD_DETAIL_KIND,
    HttpResourceSwitchDetail,
    SettingsApplyOperationEnvelope,
    SettingsApplyOperationHeader,
    SettingsApplyResultPayload,
    TaskRegistryReloadDetail,
)
from src.infrastructure.settings.settings_apply_transaction import (
    SettingsApplyTransaction,
)
from src.infrastructure.settings.settings_snapshot_store import SettingsStateHolder
from src.infrastructure.task.failed_task_recorder import (
    FailedTaskRecorder,
    TaskFailureRecord,
)
from src.infrastructure.task.task_execution_outbox_publisher import (
    TASK_EXECUTION_OUTBOX_DEFAULT_LIMIT,
    TaskExecutionOutboxPublishResult,
)
from src.infrastructure.task.task_execution_store import TaskExecutionStore
from src.infrastructure.task.task_registration_registry import (
    TaskRegistrationRegistry,
)
from src.infrastructure.task.task_runtime_manager import (
    TaskRuntimeAssembly,
    TaskRuntimeManager,
)
from src.infrastructure.task.task_worker_supervisor import TaskWorkerSupervisor


class SharedResourceLifecycle:
    """统一管理共享资源启动、重载与释放。"""

    if TYPE_CHECKING:

        def get_authorization_policy_evaluator(self) -> AuthorizationPolicyEvaluator:
            """声明授权策略评估器访问边界。"""

        def _on_task_failure_recorded(self, record: TaskFailureRecord) -> None:
            """声明任务失败监听边界。"""

        def _record_task_failure(self, record: TaskFailureRecord) -> None:
            """声明任务失败记录边界。"""

        def get_sensitive_digest_service(self) -> SensitiveDigestService:
            """声明敏感摘要服务访问边界。"""

        def get_security_event_builder(self) -> SecurityEventBuilder:
            """声明安全事件构造器访问边界。"""

        def _emit_resource_lifecycle_log(
            self,
            *,
            resource_name: str,
            lifecycle_action: ResourceLifecycleAction,
            resource_status: RuntimeResourceStatus,
            detail_text: str | None,
        ) -> None:
            """声明资源生命周期日志边界。"""

        def _flush_logs(self, *, reason: LogWriteReason) -> None:
            """声明日志刷盘边界。"""

        def emit_security_event(self, event: SecurityEventEnvelope) -> None:
            """声明安全事件写入边界。"""

        def create_unit_of_work(self) -> SqlAlchemyUnitOfWork:
            """声明工作单元创建边界。"""

        def _read_sqlalchemy_session(self, session: PersistenceSession) -> Session:
            """声明 SQLAlchemy 会话读取边界。"""

        def create_security_ip_block_repository(
            self,
            session: PersistenceSession,
        ) -> SecurityIpBlockRepository:
            """声明安全 IP 封禁仓储创建边界。"""

        def get_task_execution_store(self) -> TaskExecutionStore:
            """声明任务执行存储访问边界。"""

        def get_task_message_transport(self) -> MessageBus:
            """声明任务消息传输访问边界。"""

        def get_task_registration_registry(self) -> TaskRegistrationRegistry:
            """声明任务注册中心访问边界。"""

        def publish_reserved_task_outbox(
            self,
            *,
            limit: int = TASK_EXECUTION_OUTBOX_DEFAULT_LIMIT,
        ) -> TaskExecutionOutboxPublishResult:
            """声明任务 Outbox 发布边界。"""

        def flush_runtime_logs(self, *, reason: LogWriteReason) -> None:
            """声明运行时日志刷盘边界。"""

        def drain_pending_log_events(self) -> None:
            """声明前置日志缓冲清理边界。"""

        def record_task_failure(self, record: TaskFailureRecord) -> None:
            """声明任务失败记录边界。"""

        def get_security_ip_block_runtime(self) -> IpBlockRuntimeDetail:
            """声明安全 IP 封禁配置访问边界。"""

        def get_ip_block_guard(self) -> IpBlockGuard:
            """声明安全 IP 封禁守卫访问边界。"""

        def create_admin_identity_repository(
            self,
            session: Session,
        ) -> AdminIdentityRepositoryImpl:
            """声明管理员身份仓储创建边界。"""

        def get_password_hasher(self) -> PasswordHasher:
            """声明密码哈希器访问边界。"""

        def create_refresh_token_repository(
            self,
            session: PersistenceSession,
        ) -> RefreshTokenRepository:
            """声明刷新令牌仓储创建边界。"""

    def __init__(
        self,
        *,
        settings_holder: SettingsStateHolder,
        logger: logging.Logger,
        logger_factory: AppLoggerFactory,
        telemetry_bridge: FastApiOtelBridge,
        database_engine_factory: DatabaseEngineFactory | None = None,
    ) -> None:
        """
        初始化共享资源挂载点。
        """

        self._settings_holder = settings_holder
        self._logger = logger
        self._logger_factory = logger_factory
        self._telemetry_bridge = telemetry_bridge
        self._reload_lock = threading.RLock()
        self._request_context_manager = RequestContextManagerImpl()
        self._oauth2_scheme_provider = OAuth2SchemeProvider()
        self._authorization_policy_evaluator = AuthorizationPolicyEvaluator()
        self._authorization_guard = AuthorizationGuard(runtime_port=self)
        self._engine_factory: DatabaseEngineFactory = (
            database_engine_factory or SqlAlchemyEngineFactory()
        )
        self._alembic_runner = AlembicRunner(logger)
        self._http_resource_manager = SharedHttpResourceManager(logger=logger)
        self._runtime_resource_bootstrapper = RuntimeResourceBootstrapper()
        self._runtime_resource_releaser = RuntimeResourceReleaser()
        self._last_resource_release_result: RuntimeResourceReleaseEnvelope | None = None
        self._runtime_accessor_refresher = RuntimeAccessorRefresher()
        self._capacity_policy_resolver = RuntimeCapacityPolicyResolver()
        self._log_event_builder = LogEventBuilder()
        self._pending_log_events: list[LogEventEnvelope] = []
        self._worker_supervisor = TaskWorkerSupervisor()
        self._failed_task_recorder = FailedTaskRecorder(
            record_listener=self._on_task_failure_recorded
        )
        self._task_runtime_manager = TaskRuntimeManager(
            failed_task_recorder=self._failed_task_recorder,
            failure_callback=self._record_task_failure,
            logger=logger,
        )

        initial_settings = settings_holder.current_settings
        self._password_hasher = self._build_password_hasher(initial_settings)
        self._jwt_token_service = self._build_jwt_token_service(initial_settings)
        self._bootstrap_admin_synchronizer = BootstrapAdminSynchronizer(
            password_hasher=self._password_hasher
        )
        self._auth_failure_throttle: AuthFailureThrottle | None = None

        self._http_runtime_accessor = HttpRuntimeAccessor(resource_set=None)
        self._runtime_generation = 0
        self._session_factory: SqlAlchemySessionFactory | None = None
        self._db_session_manager: SharedDbSessionManager | None = None
        self._task_execution_store: TaskExecutionStore | None = None
        self._database_log_writer: DatabaseLogWriter | None = None
        self._log_buffer_dispatcher: LogBufferDispatcher | None = None
        self._structured_log_handler: StructuredLogHandler | None = None
        self._cache_store: CacheStore | None = None
        self._cache_service: CacheService | None = None
        self._distributed_lock_provider: DistributedLockProvider | None = None
        self._key_management_service: KeyManagementService | None = None
        self._sensitive_digest_service: SensitiveDigestService | None = None
        self._client_ip_resolver: ClientIpResolver | None = None
        self._security_event_builder: SecurityEventBuilder | None = None
        self._rate_limit_guard: RateLimitGuard | None = None
        self._ip_block_guard: IpBlockGuard | None = None
        self._risk_signal_guard: RiskSignalGuard | None = None
        self._token_binding_guard: TokenBindingGuard | None = None
        self._security_protection_guard: SecurityProtectionGuard | None = None
        self._outbound_url_safety_validator: OutboundUrlSafetyValidator | None = None
        self._task_runtime_accessor = TaskRuntimeAccessor(
            registration_registry=TaskRegistrationRegistry(
                registrations=initial_settings.modules.task.registrations
            ),
            message_bus=None,
            dispatcher=None,
            outbox_publisher=None,
            bootstrap_snapshot=None,
        )
        self._runtime_bundle = RuntimeBundle(
            settings=initial_settings,
            http_accessor=self._http_runtime_accessor,
            task_accessor=self._task_runtime_accessor,
            runtime_dependencies=self._build_runtime_dependency_set(
                settings=initial_settings,
                auth_failure_throttle=self._auth_failure_throttle,
            ),
            capacity_policy=self._capacity_policy_resolver.resolve(initial_settings),
            generation=self._runtime_generation,
        )
        self._runtime_states: dict[str, RuntimeResourceState] = {
            resource_name: RuntimeResourceState(
                resource_name=resource_name,
                status=RuntimeResourceStatus.CREATED,
            )
            for resource_name in (
                RESOURCE_HTTP_CLIENT,
                RESOURCE_ASYNC_HTTP_CLIENT,
                RESOURCE_DATABASE,
                RESOURCE_LOGGING,
                RESOURCE_CACHE,
                RESOURCE_DISTRIBUTED_LOCK,
                RESOURCE_KEY_MANAGEMENT,
                RESOURCE_SECURITY_PROTECTION,
                RESOURCE_TASK_MESSAGE_TRANSPORT,
                RESOURCE_TASK,
            )
        }
        self._ready = False
        self._enabled_web_modules: list[str] = []
        self._auth_accessor = AuthSupportAccessor(
            password_hasher=self._password_hasher,
            jwt_token_service=self._jwt_token_service,
            auth_failure_throttle=self._auth_failure_throttle,
            oauth2_scheme_provider=self._oauth2_scheme_provider,
            authorization_policy_evaluator=self._authorization_policy_evaluator,
            authorization_guard=self._authorization_guard,
        )
        self._logging_accessor = LoggingSupportAccessor(
            log_event_builder=self._log_event_builder,
            structured_log_handler=self._structured_log_handler,
            pending_log_events=self._pending_log_events,
        )

    def read_runtime_bundle(self) -> RuntimeBundle:
        """
        读取当前运行时不可变快照包。
        """

        with self._reload_lock:
            return self._runtime_bundle

    def startup(self) -> None:
        """
        启动共享资源。
        """

        settings = self.read_runtime_bundle().settings
        self._logger.info(RESOURCE_STARTUP_BEGIN_MESSAGE)
        try:
            self._runtime_resource_bootstrapper.startup(
                mount=self,
                settings=settings,
            )
            self._ready = True
            self._logger.info(RESOURCE_STARTUP_FINISH_MESSAGE)
        except Exception as exc:
            self._ready = False
            self._mark_failed_states(detail=str(exc))
            self._logger.error(RESOURCE_STARTUP_FAILED_MESSAGE, str(exc))
            raise

    def shutdown(self) -> RuntimeResourceReleaseEnvelope:
        """
        关闭共享资源。
        """

        self._logger.info(RESOURCE_RELEASE_BEGIN_MESSAGE)
        self._ready = False
        release_result = self._runtime_resource_releaser.shutdown(self)
        self._last_resource_release_result = release_result
        self._logger.info(RESOURCE_RELEASE_FINISH_MESSAGE)
        return release_result

    def apply_settings(self, settings: ApplicationSettings) -> SettingsApplyResultPayload:
        """
        应用配置，并以原子方式切换候选运行时资源。
        """

        with self._reload_lock:
            return self._apply_settings_locked(settings)

    def _apply_settings_locked(
        self,
        settings: ApplicationSettings,
    ) -> SettingsApplyResultPayload:
        """
        在重载锁内应用配置并切换候选运行时资源。
        """

        current_runtime_bundle = self._runtime_bundle
        current_settings = current_runtime_bundle.settings
        current_http_resources = current_runtime_bundle.http_accessor.resource_set
        current_registration_registry = current_runtime_bundle.task_accessor.registration_registry
        current_message_bus = current_runtime_bundle.task_accessor.message_bus
        current_dispatcher = current_runtime_bundle.task_accessor.dispatcher
        current_outbox_publisher = current_runtime_bundle.task_accessor.outbox_publisher
        current_task_snapshot = current_runtime_bundle.task_accessor.bootstrap_snapshot
        current_runtime_dependencies = self._build_runtime_dependency_set(
            settings=current_settings,
            auth_failure_throttle=self._auth_failure_throttle,
        )

        candidate_http_resources = self._http_resource_manager.build_resource_set(settings)
        candidate_registration_registry = TaskRegistrationRegistry(
            registrations=settings.modules.task.registrations
        )
        for binding in self._worker_supervisor.list_bindings():
            if not candidate_registration_registry.is_declared_job_kind(binding.job_kind):
                continue
            candidate_registration_registry.register_binding(binding)
        candidate_runtime_dependencies = self._build_runtime_dependency_set(
            settings=settings,
            auth_failure_throttle=(
                AuthFailureThrottle(
                    cache_service=self._cache_service,
                    settings=settings.runtime.auth,
                )
                if self._cache_service is not None
                else None
            ),
        )
        candidate_message_bus = self._runtime_resource_bootstrapper.build_task_message_transport(
            settings
        )
        candidate_task_runtime = self._build_task_runtime_set(
            settings=settings,
            message_bus=candidate_message_bus,
            registration_registry=candidate_registration_registry,
        )
        operation = self._build_settings_apply_operation(settings=settings)
        retired_resources: list[RetiredRuntimeResources] = []

        def commit_action() -> None:
            retired_resources.append(
                RetiredRuntimeResources(
                    http_resources=current_http_resources,
                    outbox_publisher=current_outbox_publisher,
                    dispatcher=current_dispatcher,
                    message_bus=current_message_bus,
                )
            )
            self._runtime_generation += 1
            self._settings_holder.current_settings = settings
            next_http_accessor = HttpRuntimeAccessor(resource_set=candidate_http_resources)
            next_task_accessor = TaskRuntimeAccessor(
                registration_registry=candidate_registration_registry,
                message_bus=candidate_task_runtime.message_bus,
                dispatcher=candidate_task_runtime.runtime_assembly.dispatcher,
                outbox_publisher=(candidate_task_runtime.runtime_assembly.outbox_publisher),
                bootstrap_snapshot=candidate_task_runtime.runtime_assembly.bootstrap_snapshot,
            )
            self._http_runtime_accessor = next_http_accessor
            self._task_runtime_accessor = next_task_accessor
            self._password_hasher = candidate_runtime_dependencies.password_hasher
            self._jwt_token_service = candidate_runtime_dependencies.jwt_token_service
            self._bootstrap_admin_synchronizer = (
                candidate_runtime_dependencies.bootstrap_admin_synchronizer
            )
            self._auth_failure_throttle = candidate_runtime_dependencies.auth_failure_throttle
            self._runtime_bundle = RuntimeBundle(
                settings=settings,
                http_accessor=next_http_accessor,
                task_accessor=next_task_accessor,
                runtime_dependencies=candidate_runtime_dependencies,
                capacity_policy=self._capacity_policy_resolver.resolve(settings),
                generation=self._runtime_generation,
            )
            self._refresh_accessors()
            self._logger_factory.update_level(
                self._logger,
                settings.runtime.logging.level.value,
            )
            self._apply_http_runtime_states(candidate_http_resources)
            if self._outbound_url_safety_validator is not None:
                self._outbound_url_safety_validator = OutboundUrlSafetyValidator(
                    policy=settings.runtime.security.detail.protection.outbound_url_safety,
                    digest_service=self.get_sensitive_digest_service(),
                )
                self._install_outbound_url_safety_hooks(
                    validator=self._outbound_url_safety_validator,
                    security_event_builder=self.get_security_event_builder(),
                )
            self._runtime_resource_bootstrapper.apply_message_runtime_state(
                mount=self,
                settings=settings,
            )
            self._runtime_states[RESOURCE_TASK] = self._build_state(
                RESOURCE_TASK,
                RuntimeResourceStatus.READY,
                TASK_RESOURCE_READY_DETAIL,
            )
            self._emit_resource_lifecycle_log(
                resource_name=RESOURCE_TASK,
                lifecycle_action=ResourceLifecycleAction.RELOAD,
                resource_status=RuntimeResourceStatus.READY,
                detail_text=None,
            )
            if self._log_buffer_dispatcher is not None:
                self._flush_logs(reason=LogWriteReason.MANUAL)

        def rollback_action() -> list[str]:
            candidate_task_runtime.runtime_assembly.outbox_publisher.shutdown()
            candidate_task_runtime.runtime_assembly.dispatcher.shutdown()
            candidate_task_runtime.message_bus.close()
            self._http_resource_manager.close_resource_set(candidate_http_resources)
            self._settings_holder.current_settings = current_settings
            self._http_runtime_accessor = HttpRuntimeAccessor(resource_set=current_http_resources)
            self._task_runtime_accessor = TaskRuntimeAccessor(
                registration_registry=current_registration_registry,
                message_bus=current_message_bus,
                dispatcher=current_dispatcher,
                outbox_publisher=current_outbox_publisher,
                bootstrap_snapshot=current_task_snapshot,
            )
            self._password_hasher = current_runtime_dependencies.password_hasher
            self._jwt_token_service = current_runtime_dependencies.jwt_token_service
            self._bootstrap_admin_synchronizer = (
                current_runtime_dependencies.bootstrap_admin_synchronizer
            )
            self._auth_failure_throttle = current_runtime_dependencies.auth_failure_throttle
            self._runtime_bundle = current_runtime_bundle
            self._refresh_accessors()
            self._logger_factory.update_level(
                self._logger,
                current_settings.runtime.logging.level.value,
            )
            if current_http_resources is not None:
                self._apply_http_runtime_states(current_http_resources)
            self._runtime_resource_bootstrapper.apply_message_runtime_state(
                mount=self,
                settings=current_settings,
            )
            if current_task_snapshot is not None:
                self._runtime_states[RESOURCE_TASK] = self._build_state(
                    RESOURCE_TASK,
                    RuntimeResourceStatus.READY,
                    TASK_RESOURCE_READY_DETAIL,
                )
            return [
                RESOURCE_HTTP_CLIENT,
                RESOURCE_ASYNC_HTTP_CLIENT,
                RESOURCE_TASK,
            ]

        transaction = SettingsApplyTransaction(
            operation=operation,
            active_snapshot_id=operation.header.candidate_version,
            commit_action=commit_action,
            rollback_action=rollback_action,
        )
        result = transaction.execute()
        if result.success:
            self._release_retired_runtime_resources(retired_resources)
        if not result.success and result.failure_reason is not None:
            self.emit_security_event(
                self.get_security_event_builder().build_config_security_rejected_event(
                    reason_code=result.failure_reason,
                )
            )
        return result

    def _release_retired_runtime_resources(
        self,
        retired_resources: list[RetiredRuntimeResources],
    ) -> None:
        """
        在运行时包切换成功后延迟释放旧资源。

        :param retired_resources: 待释放旧资源集合。
        :type retired_resources: list[RetiredRuntimeResources]
        :returns: 无返回值。
        :rtype: None
        """

        for retired_resource in retired_resources:
            if retired_resource.http_resources is not None:
                self._http_resource_manager.close_resource_set(retired_resource.http_resources)
            if retired_resource.outbox_publisher is not None:
                retired_resource.outbox_publisher.shutdown()
            if retired_resource.dispatcher is not None:
                retired_resource.dispatcher.shutdown()
            if retired_resource.message_bus is not None:
                retired_resource.message_bus.close()

    def get_runtime_states(self) -> list[RuntimeResourceState]:
        """
        获取运行时状态集合。
        """

        return [state.model_copy(deep=True) for state in self._runtime_states.values()]

    def get_last_resource_release_result(
        self,
    ) -> RuntimeResourceReleaseEnvelope | None:
        """
        获取最近一次资源释放结果。

        :returns: 返回最近一次资源释放信封副本；尚未释放时返回 ``None``。
        :rtype: RuntimeResourceReleaseEnvelope | None
        """

        if self._last_resource_release_result is None:
            return None
        return self._last_resource_release_result.model_copy(deep=True)

    def is_ready(self) -> bool:
        """
        获取是否就绪。
        """

        return self._ready

    def set_enabled_web_modules(self, enabled_web_modules: list[str]) -> None:
        """
        设置启用 Web 模块集合。
        """

        self._enabled_web_modules = list(enabled_web_modules)

    def get_enabled_web_modules(self) -> list[str]:
        """
        获取启用 Web 模块集合。
        """

        return list(self._enabled_web_modules)

    def read_application_settings_snapshot(
        self,
    ) -> ApplicationSettingsSnapshot:
        """
        读取应用配置只读快照。
        """

        settings = self.read_runtime_bundle().settings
        return ApplicationSettingsSnapshot(
            application_name=settings.app.name,
            version=settings.app.version,
            environment=settings.app.environment.value,
            system_overview_title=settings.modules.system.overview_title,
            ready_probe_enabled=settings.modules.system.ready_probe_enabled,
            enabled_modules=self.get_enabled_web_modules(),
            ready=self.is_ready(),
            runtime_states=self.get_runtime_states(),
        )

    def build_http_resource_set(
        self,
        settings: ApplicationSettings,
    ) -> SharedHttpResourceSet:
        """
        构建 HTTP 运行时资源集合。

        :param settings: 已通过校验的应用配置。
        :type settings: ApplicationSettings
        :returns: 返回 HTTP 运行时资源集合。
        :rtype: SharedHttpResourceSet
        """

        return self._http_resource_manager.build_resource_set(settings)

    def close_http_resource_set(self, resource_set: SharedHttpResourceSet) -> None:
        """
        关闭 HTTP 运行时资源集合。

        :param resource_set: 待关闭的 HTTP 运行时资源集合。
        :type resource_set: SharedHttpResourceSet
        :returns: 无返回值。
        :rtype: None
        """

        self._http_resource_manager.close_resource_set(resource_set)

    def attach_http_runtime(
        self,
        resource_set: SharedHttpResourceSet,
    ) -> RuntimeResourceMountOperationEnvelope:
        """
        挂载 HTTP 运行时资源集合。

        :param resource_set: 已构建完成的 HTTP 运行时资源集合。
        :type resource_set: SharedHttpResourceSet
        :returns: 返回 HTTP 资源挂载操作信封。
        :rtype: RuntimeResourceMountOperationEnvelope
        """

        with self._reload_lock:
            current_bundle = self._runtime_bundle
            next_http_accessor = HttpRuntimeAccessor(resource_set=resource_set)
            self._http_runtime_accessor = next_http_accessor
            self._runtime_generation += 1
            self._runtime_bundle = RuntimeBundle(
                settings=current_bundle.settings,
                http_accessor=next_http_accessor,
                task_accessor=current_bundle.task_accessor,
                runtime_dependencies=self._build_runtime_dependency_set(
                    settings=current_bundle.settings,
                    auth_failure_throttle=self._auth_failure_throttle,
                ),
                capacity_policy=current_bundle.capacity_policy,
                generation=self._runtime_generation,
            )
            self._apply_http_runtime_states(resource_set)
        return self._build_mount_operation(
            resource_name=RESOURCE_HTTP_CLIENT,
            operation_name=ATTACH_HTTP_RUNTIME_OPERATION_NAME,
            detail=HttpRuntimeAttachedDetail(
                kind=HTTP_RUNTIME_ATTACHED_KIND,
                sync_status=resource_set.http_state.status,
                async_status=resource_set.async_http_state.status,
            ),
        )

    def detach_http_runtime(self) -> SharedHttpResourceSet | None:
        """
        卸载 HTTP 运行时资源集合。

        :returns: 返回卸载前的 HTTP 运行时资源集合；未挂载时返回 ``None``。
        :rtype: SharedHttpResourceSet | None
        """

        with self._reload_lock:
            current_bundle = self._runtime_bundle
            resource_set = current_bundle.http_accessor.resource_set
            next_http_accessor = HttpRuntimeAccessor(resource_set=None)
            self._http_runtime_accessor = next_http_accessor
            self._runtime_generation += 1
            self._runtime_bundle = RuntimeBundle(
                settings=current_bundle.settings,
                http_accessor=next_http_accessor,
                task_accessor=current_bundle.task_accessor,
                runtime_dependencies=self._build_runtime_dependency_set(
                    settings=current_bundle.settings,
                    auth_failure_throttle=self._auth_failure_throttle,
                ),
                capacity_policy=current_bundle.capacity_policy,
                generation=self._runtime_generation,
            )
            return resource_set

    def build_validated_database_engine(
        self,
        settings: DatabaseRuntimeSettings,
    ) -> Engine:
        """
        构建并校验数据库引擎。

        :param settings: 数据库运行时配置。
        :type settings: DatabaseRuntimeSettings
        :returns: 返回已通过校验的 SQLAlchemy 引擎。
        :rtype: Engine
        """

        engine = self._engine_factory.build(settings)
        self._engine_factory.validate(engine)
        return engine

    def upgrade_database_schema_if_enabled(
        self,
        settings: ApplicationSettings,
    ) -> None:
        """
        按配置执行数据库迁移。

        :param settings: 已通过校验的应用配置。
        :type settings: ApplicationSettings
        :returns: 无返回值。
        :rtype: None
        """

        if settings.runtime.database.auto_upgrade_on_startup:
            self._alembic_runner.upgrade_head(settings.runtime.database)

    def bootstrap_admin_identity(self, settings: ApplicationSettings) -> None:
        """
        引导管理员身份。

        :param settings: 已通过校验的应用配置。
        :type settings: ApplicationSettings
        :returns: 无返回值。
        :rtype: None
        """

        self._bootstrap_admin_identity(settings)

    def install_database_runtime(
        self,
        *,
        session_factory: SqlAlchemySessionFactory,
        db_session_manager: SharedDbSessionManager,
        task_execution_store: TaskExecutionStore,
    ) -> RuntimeResourceMountOperationEnvelope:
        """
        挂载数据库运行时资源。

        :param session_factory: SQLAlchemy 会话工厂。
        :type session_factory: SqlAlchemySessionFactory
        :param db_session_manager: 共享数据库会话管理器。
        :type db_session_manager: SharedDbSessionManager
        :param task_execution_store: 任务执行记录存储。
        :type task_execution_store: TaskExecutionStore
        :returns: 返回数据库资源挂载操作信封。
        :rtype: RuntimeResourceMountOperationEnvelope
        """

        self._session_factory = session_factory
        self._db_session_manager = db_session_manager
        self._task_execution_store = task_execution_store
        return self._build_mount_operation(
            resource_name=RESOURCE_DATABASE,
            operation_name=INSTALL_DATABASE_RUNTIME_OPERATION_NAME,
            detail=DatabaseRuntimeAttachedDetail(
                kind=DATABASE_RUNTIME_ATTACHED_KIND,
                session_factory_attached=True,
                session_manager_attached=True,
                task_execution_store_attached=True,
            ),
        )

    def clear_database_runtime(self) -> None:
        """
        清空数据库运行时资源。

        :returns: 无返回值。
        :rtype: None
        """

        if self._db_session_manager is not None:
            self._db_session_manager.close()
        self._db_session_manager = None
        self._session_factory = None
        self._task_execution_store = None

    def get_database_session_manager(self) -> SharedDbSessionManager | None:
        """
        获取内部数据库会话管理器。

        :returns: 返回数据库会话管理器；未就绪时返回 ``None``。
        :rtype: SharedDbSessionManager | None
        """

        return self._db_session_manager

    def get_runtime_logger(self) -> logging.Logger:
        """
        获取资源运行时日志记录器。

        :returns: 返回资源运行时日志记录器。
        :rtype: logging.Logger
        """

        return self._logger

    def configure_runtime_structured_log_handler(
        self,
        structured_log_handler: StructuredLogHandler,
    ) -> None:
        """
        配置运行时结构化日志处理器。

        :param structured_log_handler: 结构化日志处理器。
        :type structured_log_handler: StructuredLogHandler
        :returns: 无返回值。
        :rtype: None
        """

        self._logger_factory.configure_structured_handler(
            self._logger,
            structured_log_handler,
        )

    def install_logging_runtime(
        self,
        *,
        database_log_writer: DatabaseLogWriter,
        log_buffer_dispatcher: LogBufferDispatcher,
        structured_log_handler: StructuredLogHandler,
    ) -> RuntimeResourceMountOperationEnvelope:
        """
        挂载日志运行时资源。

        :param database_log_writer: 数据库日志写入器。
        :type database_log_writer: DatabaseLogWriter
        :param log_buffer_dispatcher: 日志缓冲调度器。
        :type log_buffer_dispatcher: LogBufferDispatcher
        :param structured_log_handler: 结构化日志处理器。
        :type structured_log_handler: StructuredLogHandler
        :returns: 返回日志资源挂载操作信封。
        :rtype: RuntimeResourceMountOperationEnvelope
        """

        self._database_log_writer = database_log_writer
        self._log_buffer_dispatcher = log_buffer_dispatcher
        self._structured_log_handler = structured_log_handler
        return self._build_mount_operation(
            resource_name=RESOURCE_LOGGING,
            operation_name=INSTALL_LOGGING_RUNTIME_OPERATION_NAME,
            detail=LoggingRuntimeAttachedDetail(
                kind=LOGGING_RUNTIME_ATTACHED_KIND,
                database_writer_attached=True,
                buffer_dispatcher_attached=True,
                structured_handler_attached=True,
            ),
        )

    def clear_logging_runtime(self) -> None:
        """
        清空日志运行时资源。

        :returns: 无返回值。
        :rtype: None
        """

        self._logger_factory.remove_structured_handlers(self._logger)
        if self._log_buffer_dispatcher is not None:
            self._log_buffer_dispatcher.shutdown()
        self._structured_log_handler = None
        self._log_buffer_dispatcher = None
        self._database_log_writer = None
        self.refresh_runtime_accessors()

    def install_cache_runtime(
        self,
        *,
        cache_store: CacheStore,
        cache_service: CacheService,
        auth_failure_throttle: AuthFailureThrottle,
    ) -> RuntimeResourceMountOperationEnvelope:
        """
        挂载缓存运行时资源。

        :param cache_store: 缓存存储。
        :type cache_store: CacheStore
        :param cache_service: 缓存服务。
        :type cache_service: CacheService
        :param auth_failure_throttle: 鉴权失败节流器。
        :type auth_failure_throttle: AuthFailureThrottle
        :returns: 返回缓存资源挂载操作信封。
        :rtype: RuntimeResourceMountOperationEnvelope
        """

        self._cache_store = cache_store
        self._cache_service = cache_service
        self._auth_failure_throttle = auth_failure_throttle
        return self._build_mount_operation(
            resource_name=RESOURCE_CACHE,
            operation_name=INSTALL_CACHE_RUNTIME_OPERATION_NAME,
            detail=CacheRuntimeAttachedDetail(
                kind=CACHE_RUNTIME_ATTACHED_KIND,
                cache_store_attached=True,
                cache_service_attached=True,
                auth_failure_throttle_attached=True,
            ),
        )

    def install_security_infrastructure(
        self,
        settings: ApplicationSettings,
    ) -> None:
        """
        挂载分布式锁、密钥管理和安全防护基础设施。
        """

        if self._cache_store is None:
            raise HttpFaultException(
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                error_code=CoreErrorCode.RESOURCE_NOT_READY,
                message=CACHE_STORE_NOT_READY_MESSAGE,
            )
        key_builder = CacheKeyBuilder(key_prefix=settings.runtime.cache.key_prefix)
        digest_service = SensitiveDigestService(
            salt=settings.runtime.auth.jwt_secret.get_secret_value()
        )
        client_ip_resolver = self._build_client_ip_resolver(settings)
        security_event_builder = SecurityEventBuilder()
        distributed_lock_provider = DistributedLockProvider(
            cache_store=self._cache_store,
            key_builder=key_builder,
            enabled=settings.runtime.distributed_lock.header.enabled,
        )
        key_ring_store = DatabaseKeyRingStore(
            unit_of_work_factory=self.create_unit_of_work,
            cache_store=self._cache_store,
            key_builder=key_builder,
            encryption_secret=settings.runtime.auth.jwt_secret.get_secret_value(),
        )
        key_management_service = KeyManagementService(
            key_ring_store=key_ring_store,
            key_rotation_service=KeyRotationService(),
            distributed_lock_provider=distributed_lock_provider,
            rotation_lock_lease_seconds=settings.runtime.distributed_lock.detail.lease_seconds,
            rotation_lock_wait_seconds=settings.runtime.distributed_lock.detail.wait_seconds,
        )
        for key_family in settings.runtime.key_management.detail.key_families:
            if key_family.enabled:
                key_management_service.initialize_key_family(key_family)
        rate_limit_guard = RateLimitGuard(
            cache_store=self._cache_store,
            key_builder=key_builder,
            digest_service=digest_service,
            client_ip_resolver=client_ip_resolver,
        )
        ip_block_guard = IpBlockGuard(
            cache_store=self._cache_store,
            key_builder=key_builder,
            digest_service=digest_service,
            lock_provider=distributed_lock_provider,
            unit_of_work_factory=self.create_unit_of_work,
            repository_factory=self.create_security_ip_block_repository,
            client_ip_resolver=client_ip_resolver,
        )
        self._distributed_lock_provider = distributed_lock_provider
        self._key_management_service = key_management_service
        self._jwt_token_service = self._build_jwt_token_service(
            settings,
            key_management_service=key_management_service,
        )
        self._sensitive_digest_service = digest_service
        self._client_ip_resolver = client_ip_resolver
        self._log_event_builder.client_ip_resolver = client_ip_resolver
        self._security_event_builder = security_event_builder
        self._rate_limit_guard = rate_limit_guard
        self._ip_block_guard = ip_block_guard
        self._risk_signal_guard = RiskSignalGuard(
            cache_store=self._cache_store,
            key_builder=key_builder,
            digest_service=digest_service,
        )
        self._token_binding_guard = TokenBindingGuard(
            cache_store=self._cache_store,
            key_builder=key_builder,
            digest_service=digest_service,
        )
        self._security_protection_guard = SecurityProtectionGuard(
            ip_block_guard=ip_block_guard,
            rate_limit_guard=rate_limit_guard,
            risk_signal_guard=self._risk_signal_guard,
            client_ip_resolver=client_ip_resolver,
            security_event_builder=security_event_builder,
        )
        self._outbound_url_safety_validator = OutboundUrlSafetyValidator(
            policy=settings.runtime.security.detail.protection.outbound_url_safety,
            digest_service=digest_service,
        )
        self._install_outbound_url_safety_hooks(
            validator=self._outbound_url_safety_validator,
            security_event_builder=security_event_builder,
        )
        self.mark_runtime_resource_ready(RESOURCE_DISTRIBUTED_LOCK)
        self.mark_runtime_resource_ready(RESOURCE_KEY_MANAGEMENT)
        self.mark_runtime_resource_ready(RESOURCE_SECURITY_PROTECTION)

    def _build_client_ip_resolver(
        self,
        settings: ApplicationSettings,
    ) -> ClientIpResolver:
        """
        按安全运行时配置构建客户端 IP 解析器。
        """

        client_ip_detail = settings.runtime.security.detail.protection.client_ip
        return ClientIpResolver(
            trusted_proxy_policy=TrustedProxyPolicy(
                cidr_blocks=tuple(client_ip_detail.trusted_proxy_cidr_blocks)
            )
        )

    def _install_outbound_url_safety_hooks(
        self,
        *,
        validator: OutboundUrlSafetyValidator,
        security_event_builder: SecurityEventBuilder,
    ) -> None:
        """
        安装出站 URL 安全钩子。
        """

        if self._http_runtime_accessor.resource_set is None:
            return
        self._http_runtime_accessor.resource_set.http_client.install_url_safety_hook(
            SyncOutboundUrlSafetyHook(
                validator=validator,
                request_context_manager=self._request_context_manager,
                security_event_builder=security_event_builder,
                security_event_emitter=self,
            )
        )
        async_http_client = self._http_runtime_accessor.resource_set.async_http_client
        if async_http_client is None:
            return
        async_http_client.install_url_safety_hook(
            AsyncOutboundUrlSafetyHook(
                validator=validator,
                request_context_manager=self._request_context_manager,
                security_event_builder=security_event_builder,
                security_event_emitter=self,
            )
        )

    def clear_cache_runtime(self) -> None:
        """
        清空缓存运行时资源。

        :returns: 无返回值。
        :rtype: None
        """

        if self._cache_store is not None:
            self._cache_store.close()
        self._cache_store = None
        self._cache_service = None
        self._auth_failure_throttle = None
        self._distributed_lock_provider = None
        self._key_management_service = None
        self._sensitive_digest_service = None
        self._client_ip_resolver = None
        self._security_event_builder = None
        self._rate_limit_guard = None
        self._ip_block_guard = None
        self._risk_signal_guard = None
        self._token_binding_guard = None
        self._security_protection_guard = None
        self._outbound_url_safety_validator = None
        self.refresh_runtime_accessors()

    def build_task_runtime_assembly(
        self,
        *,
        settings: ApplicationSettings,
        message_bus: MessageBus,
        registration_registry: TaskRegistrationRegistry,
    ) -> TaskRuntimeAssembly:
        """
        构建任务运行时装配结果。

        :param settings: 已通过校验的应用配置。
        :type settings: ApplicationSettings
        :param message_bus: 当前消息总线。
        :type message_bus: MessageBus
        :param registration_registry: 当前任务注册中心。
        :type registration_registry: TaskRegistrationRegistry
        :returns: 返回任务运行时装配结果。
        :rtype: TaskRuntimeAssembly
        """

        return self._task_runtime_manager.build_runtime(
            settings=settings,
            message_bus=message_bus,
            registration_registry=registration_registry,
            task_execution_store=self.get_task_execution_store(),
        )

    def install_task_runtime(
        self,
        *,
        registration_registry: TaskRegistrationRegistry,
        message_bus: MessageBus,
        runtime_assembly: TaskRuntimeAssembly,
    ) -> RuntimeResourceMountOperationEnvelope:
        """
        挂载任务运行时资源。

        :param registration_registry: 当前任务注册中心。
        :type registration_registry: TaskRegistrationRegistry
        :param message_bus: 当前消息总线。
        :type message_bus: MessageBus
        :param runtime_assembly: 任务运行时装配结果。
        :type runtime_assembly: TaskRuntimeAssembly
        :returns: 返回任务资源挂载操作信封。
        :rtype: RuntimeResourceMountOperationEnvelope
        """

        with self._reload_lock:
            current_bundle = self._runtime_bundle
            next_task_accessor = TaskRuntimeAccessor(
                registration_registry=registration_registry,
                message_bus=message_bus,
                dispatcher=runtime_assembly.dispatcher,
                outbox_publisher=runtime_assembly.outbox_publisher,
                bootstrap_snapshot=runtime_assembly.bootstrap_snapshot,
            )
            self._task_runtime_accessor = next_task_accessor
            self._runtime_generation += 1
            self._runtime_bundle = RuntimeBundle(
                settings=current_bundle.settings,
                http_accessor=current_bundle.http_accessor,
                task_accessor=next_task_accessor,
                runtime_dependencies=self._build_runtime_dependency_set(
                    settings=current_bundle.settings,
                    auth_failure_throttle=self._auth_failure_throttle,
                ),
                capacity_policy=current_bundle.capacity_policy,
                generation=self._runtime_generation,
            )
        return self._build_mount_operation(
            resource_name=RESOURCE_TASK,
            operation_name=INSTALL_TASK_RUNTIME_OPERATION_NAME,
            detail=TaskRuntimeAttachedDetail(
                kind=TASK_RUNTIME_ATTACHED_KIND,
                registration_count=len(registration_registry.list_bindings()),
                message_bus_attached=True,
                dispatcher_attached=True,
                bootstrap_snapshot_attached=True,
            ),
        )

    def clear_task_runtime(self) -> None:
        """
        清空任务运行时资源并保留任务注册中心。

        :returns: 无返回值。
        :rtype: None
        """

        with self._reload_lock:
            current_bundle = self._runtime_bundle
            current_task_accessor = current_bundle.task_accessor
            if current_task_accessor.outbox_publisher is not None:
                current_task_accessor.outbox_publisher.shutdown()
            if current_task_accessor.dispatcher is not None:
                current_task_accessor.dispatcher.shutdown()
            if current_task_accessor.message_bus is not None:
                current_task_accessor.message_bus.close()
            next_task_accessor = TaskRuntimeAccessor(
                registration_registry=current_task_accessor.registration_registry,
                message_bus=None,
                dispatcher=None,
                outbox_publisher=None,
                bootstrap_snapshot=None,
            )
            self._task_runtime_accessor = next_task_accessor
            self._runtime_generation += 1
            self._runtime_bundle = RuntimeBundle(
                settings=current_bundle.settings,
                http_accessor=current_bundle.http_accessor,
                task_accessor=next_task_accessor,
                runtime_dependencies=self._build_runtime_dependency_set(
                    settings=current_bundle.settings,
                    auth_failure_throttle=self._auth_failure_throttle,
                ),
                capacity_policy=current_bundle.capacity_policy,
                generation=self._runtime_generation,
            )

    def refresh_runtime_accessors(
        self,
    ) -> RuntimeResourceMountOperationEnvelope:
        """
        刷新鉴权与日志访问器快照。

        :returns: 返回访问器刷新操作信封。
        :rtype: RuntimeResourceMountOperationEnvelope
        """

        snapshot = self._runtime_accessor_refresher.refresh(
            password_hasher=self._password_hasher,
            jwt_token_service=self._jwt_token_service,
            auth_failure_throttle=self._auth_failure_throttle,
            oauth2_scheme_provider=self._oauth2_scheme_provider,
            authorization_policy_evaluator=self._authorization_policy_evaluator,
            authorization_guard=self._authorization_guard,
            log_event_builder=self._log_event_builder,
            structured_log_handler=self._structured_log_handler,
            pending_log_events=self._pending_log_events,
        )
        self._auth_accessor = snapshot.auth_accessor
        self._logging_accessor = snapshot.logging_accessor
        return self._build_mount_operation(
            resource_name=RESOURCE_LOGGING,
            operation_name=REFRESH_RUNTIME_ACCESSORS_OPERATION_NAME,
            detail=RuntimeAccessorsRefreshedDetail(
                kind=RUNTIME_ACCESSORS_REFRESHED_KIND,
                auth_accessor_refreshed=True,
                logging_accessor_refreshed=True,
            ),
        )

    def mark_runtime_resource_state(
        self,
        resource_name: str,
        status: RuntimeResourceStatus,
        detail: str | None = None,
    ) -> RuntimeResourceMountOperationEnvelope:
        """
        标记运行时资源状态。

        :param resource_name: 运行时资源名称。
        :type resource_name: str
        :param status: 目标运行时资源状态。
        :type status: RuntimeResourceStatus
        :param detail: 状态诊断详情。默认值：``None``。
        :type detail: str | None
        :returns: 返回状态变更操作信封。
        :rtype: RuntimeResourceMountOperationEnvelope
        """

        self._runtime_states[resource_name] = self._build_state(
            resource_name,
            status,
            detail,
        )
        return self._build_mount_operation(
            resource_name=resource_name,
            operation_name=MARK_RUNTIME_RESOURCE_STATE_OPERATION_NAME,
            detail=RuntimeResourceStateChangedDetail(
                kind=RUNTIME_RESOURCE_STATE_CHANGED_KIND,
                status=status,
                detail=detail,
            ),
        )

    def mark_runtime_resource_ready(
        self,
        resource_name: str,
        detail: str | None = None,
    ) -> RuntimeResourceMountOperationEnvelope:
        """
        标记运行时资源就绪。

        :param resource_name: 运行时资源名称。
        :type resource_name: str
        :param detail: 状态诊断详情。默认值：``None``。
        :type detail: str | None
        :returns: 返回状态变更操作信封。
        :rtype: RuntimeResourceMountOperationEnvelope
        """

        return self.mark_runtime_resource_state(
            resource_name,
            RuntimeResourceStatus.READY,
            detail,
        )

    def mark_runtime_resource_stopped(
        self,
        resource_name: str,
    ) -> RuntimeResourceMountOperationEnvelope:
        """
        标记运行时资源停止。

        :param resource_name: 运行时资源名称。
        :type resource_name: str
        :returns: 返回状态变更操作信封。
        :rtype: RuntimeResourceMountOperationEnvelope
        """

        return self.mark_runtime_resource_state(
            resource_name,
            RuntimeResourceStatus.STOPPED,
        )

    def emit_runtime_lifecycle_log(
        self,
        *,
        resource_name: str,
        lifecycle_action: ResourceLifecycleAction,
        resource_status: RuntimeResourceStatus,
        detail_text: str | None,
    ) -> None:
        """
        发送运行时资源生命周期日志。

        :param resource_name: 运行时资源名称。
        :type resource_name: str
        :param lifecycle_action: 生命周期动作。
        :type lifecycle_action: ResourceLifecycleAction
        :param resource_status: 运行时资源状态。
        :type resource_status: RuntimeResourceStatus
        :param detail_text: 诊断详情文本。
        :type detail_text: str | None
        :returns: 无返回值。
        :rtype: None
        """

        self._emit_resource_lifecycle_log(
            resource_name=resource_name,
            lifecycle_action=lifecycle_action,
            resource_status=resource_status,
            detail_text=detail_text,
        )

    def _build_runtime_dependency_set(
        self,
        *,
        settings: ApplicationSettings,
        auth_failure_throttle: AuthFailureThrottle | None,
    ) -> RuntimeDependencySet:
        """
        构建运行时依赖集合。
        """

        password_hasher = self._build_password_hasher(settings)
        jwt_token_service = self._build_jwt_token_service(settings)
        return RuntimeDependencySet(
            password_hasher=password_hasher,
            jwt_token_service=jwt_token_service,
            bootstrap_admin_synchronizer=BootstrapAdminSynchronizer(
                password_hasher=password_hasher
            ),
            auth_failure_throttle=auth_failure_throttle,
        )

    def _build_task_runtime_set(
        self,
        *,
        settings: ApplicationSettings,
        message_bus: MessageBus,
        registration_registry: TaskRegistrationRegistry,
    ) -> TaskRuntimeSet:
        """
        构建任务运行时集合。
        """

        runtime_assembly = self._task_runtime_manager.build_runtime(
            settings=settings,
            message_bus=message_bus,
            registration_registry=registration_registry,
            task_execution_store=self.get_task_execution_store(),
        )
        return TaskRuntimeSet(
            registration_registry=registration_registry,
            message_bus=message_bus,
            runtime_assembly=runtime_assembly,
        )

    def _build_settings_apply_operation(
        self,
        *,
        settings: ApplicationSettings,
    ) -> SettingsApplyOperationEnvelope:
        """
        构建配置应用操作信封。
        """

        switched_resources = [
            RESOURCE_HTTP_CLIENT,
            RESOURCE_ASYNC_HTTP_CLIENT,
            RESOURCE_TASK,
        ]
        task_detail = TaskRegistryReloadDetail(
            kind=TASK_REGISTRY_RELOAD_DETAIL_KIND,
            registered_job_kinds=[
                registration.header.job_kind for registration in settings.modules.task.registrations
            ],
            restored_job_kinds=[
                binding.job_kind for binding in self._worker_supervisor.list_bindings()
            ],
        )
        operation_digest = hashlib.sha256(settings.model_dump_json().encode("utf-8")).hexdigest()
        return SettingsApplyOperationEnvelope(
            header=SettingsApplyOperationHeader(
                operation_name=SETTINGS_APPLY_OPERATION_NAME,
                target_resource=SETTINGS_APPLY_TARGET_RESOURCE,
                candidate_version=operation_digest[:12],
            ),
            detail=(
                HttpResourceSwitchDetail(
                    kind=HTTP_RESOURCE_SWITCH_DETAIL_KIND,
                    switched_resources=switched_resources,
                    rollback_resources=switched_resources,
                )
                if len(task_detail.registered_job_kinds) == 0
                else task_detail
            ),
        )

    def _apply_http_runtime_states(self, resource_set: SharedHttpResourceSet) -> None:
        """
        应用 HTTP 运行时状态。
        """

        self._runtime_states[RESOURCE_HTTP_CLIENT] = resource_set.http_state.model_copy(deep=True)
        self._runtime_states[RESOURCE_ASYNC_HTTP_CLIENT] = resource_set.async_http_state.model_copy(
            deep=True
        )

    def _bootstrap_admin_identity(
        self,
        settings: ApplicationSettings,
    ) -> None:
        """
        处理引导管理员身份。
        """

        bootstrap_admin = settings.modules.auth.bootstrap_admin
        if not bootstrap_admin.enabled:
            return
        if settings.app.environment == AppEnvironment.PRODUCTION:
            self._logger.critical(PRODUCTION_BOOTSTRAP_ADMIN_BLOCKED_MESSAGE)
            raise HttpFaultException(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                error_code=CoreErrorCode.CONFIG_INVALID,
                message=PRODUCTION_BOOTSTRAP_ADMIN_BLOCKED_MESSAGE,
            )
        unit_of_work = self.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            self._bootstrap_admin_synchronizer.synchronize(
                session=session,
                bootstrap_admin=bootstrap_admin,
            )
            unit_of_work.commit()
        except Exception:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()

    def _build_password_hasher(self, settings: ApplicationSettings) -> PasswordHasher:
        """
        构建密码哈希器。
        """

        return PasswordHasher(settings.runtime.auth.password_hash_algorithm)

    def _build_jwt_token_service(
        self,
        settings: ApplicationSettings,
        *,
        key_management_service: KeyManagementService | None = None,
    ) -> JwtTokenService:
        """
        构建 JWT 令牌服务。
        """

        return JwtTokenService(
            AccessTokenPolicy(
                jwt_secret=settings.runtime.auth.jwt_secret.get_secret_value(),
                jwt_algorithm=settings.runtime.auth.jwt_algorithm,
                access_token_expires_in_seconds=settings.runtime.auth.access_token_expires_in_seconds,
                refresh_token_expires_in_seconds=settings.runtime.auth.refresh_token_expires_in_seconds,
                issuer=settings.runtime.auth.issuer,
                audience=settings.runtime.auth.audience,
                refresh_token_rotation_enabled=settings.runtime.auth.refresh_token_rotation_enabled,
            ),
            key_management_service=key_management_service,
        )

    def _build_state(
        self,
        resource_name: str,
        status: RuntimeResourceStatus,
        detail: str | None = None,
    ) -> RuntimeResourceState:
        """
        构建状态。
        """

        return RuntimeResourceState(
            resource_name=resource_name,
            status=status,
            detail=detail,
        )

    def _build_mount_operation(
        self,
        *,
        resource_name: str,
        operation_name: str,
        detail: RuntimeResourceMountOperationDetail,
    ) -> RuntimeResourceMountOperationEnvelope:
        """
        构建资源挂载操作信封。

        :param resource_name: 运行时资源名称。
        :type resource_name: str
        :param operation_name: 操作名称。
        :type operation_name: str
        :param detail: 资源挂载强类型扩展字段。
        :type detail: RuntimeResourceMountOperationDetail
        :returns: 返回资源挂载操作信封。
        :rtype: RuntimeResourceMountOperationEnvelope
        """

        return RuntimeResourceMountOperationEnvelope(
            header=RuntimeResourceMountOperationHeader(
                kind=detail.kind,
                operation_name=operation_name,
                resource_name=resource_name,
            ),
            detail=detail,
        )

    def _mark_failed_states(self, *, detail: str) -> None:
        """
        标记失败状态集合。
        """

        for resource_name, state in self._runtime_states.items():
            if state.status in {
                RuntimeResourceStatus.READY,
                RuntimeResourceStatus.STOPPED,
            }:
                continue
            self._runtime_states[resource_name] = self._build_state(
                resource_name,
                RuntimeResourceStatus.FAILED,
                detail,
            )
            self._emit_resource_lifecycle_log(
                resource_name=resource_name,
                lifecycle_action=ResourceLifecycleAction.STARTUP,
                resource_status=RuntimeResourceStatus.FAILED,
                detail_text=detail,
            )

    def _refresh_accessors(self) -> None:
        """
        刷新鉴权与日志访问器快照。
        """

        self.refresh_runtime_accessors()
