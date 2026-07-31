"""
运行时资源启动装配器。
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.core.cache_contract.cache_runtime_contract import (
    CacheBackend,
    MemoryCacheBackendDetail,
    RedisCacheBackendDetail,
)
from src.core.cache_contract.cache_store_contract import CacheStore
from src.core.exception_contract.error_code_catalog_contract import CoreErrorCode
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.http_contract.runtime_resource_contract import RuntimeResourceStatus
from src.core.logging_contract.log_event_contract import ResourceLifecycleAction
from src.core.logging_contract.log_runtime_contract import DatabaseLogSinkDetail
from src.core.task_contract.message_bus_contract import MessageBus
from src.core.task_contract.task_dispatcher_contract import TaskFailureStage
from src.core.task_contract.task_runtime_contract import (
    LocalMessageBackendDetail,
    MessageBackend,
    RabbitMqMessageBackendDetail,
    TaskBackend,
)
from src.infrastructure.auth.auth_failure_throttle import AuthFailureThrottle
from src.infrastructure.cache.cache_key_builder import CacheKeyBuilder
from src.infrastructure.cache.cache_payload_codec import CachePayloadCodec
from src.infrastructure.cache.cache_policy_resolver import CachePolicyResolver
from src.infrastructure.cache.cache_service import CacheService
from src.infrastructure.cache.memory_cache_store import MemoryCacheStore
from src.infrastructure.cache.redis_cache_store import RedisCacheStore
from src.infrastructure.logging.database_log_writer import DatabaseLogWriter
from src.infrastructure.logging.log_buffer_dispatcher import LogBufferDispatcher
from src.infrastructure.logging.logging_entry_environment_bridge import (
    LoggingEntryEnvironmentBridge,
)
from src.infrastructure.logging.structured_log_handler import StructuredLogHandler
from src.infrastructure.persistence.sqlalchemy_session_factory import (
    SqlAlchemySessionFactory,
)
from src.infrastructure.resource_slot.shared_db_session_manager import (
    SharedDbSessionManager,
)
from src.infrastructure.task.failed_task_recorder import TaskFailureRecord
from src.infrastructure.task.local_message_bus import LocalMessageBus
from src.infrastructure.task.rabbitmq_message_bus import RabbitMqMessageBus
from src.infrastructure.task.rabbitmq_message_gateway import RabbitMqMessageGateway
from src.infrastructure.task.task_execution_store import TaskExecutionStore

if TYPE_CHECKING:
    from src.infrastructure.resource_mount.shared_resource_lifecycle import SharedResourceLifecycle
    from src.infrastructure.settings.application_settings import ApplicationSettings

RUNTIME_RESOURCE_OPERATION_SCHEMA_VERSION: Final = "1.0"
RESOURCE_BOOTSTRAP_KIND: Final = "resource_bootstrap"
RESOURCE_BOOTSTRAP_OPERATION_NAME = "startup"
RESOURCE_BOOTSTRAP_TARGET_RESOURCE = "shared_resource_mount"
STARTUP_PROBE_RETRY_COUNT = 0
MESSAGE_RESOURCE_DETAIL_SEPARATOR = " "
LOCAL_TASK_RABBITMQ_MESSAGE_BLOCKED_MESSAGE = (
    "本地任务后端禁止搭配 RabbitMQ 消息总线，避免重复执行。"
)


class RuntimeResourceOperationHeader(BaseModel):
    """
    运行时资源操作公共头。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["resource_bootstrap"] = RESOURCE_BOOTSTRAP_KIND
    schema_version: Literal["1.0"] = RUNTIME_RESOURCE_OPERATION_SCHEMA_VERSION
    operation_name: str
    target_resource: str


class ResourceBootstrapDetail(BaseModel):
    """
    资源启动扩展。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["resource_bootstrap"] = RESOURCE_BOOTSTRAP_KIND
    schema_version: Literal["1.0"] = RUNTIME_RESOURCE_OPERATION_SCHEMA_VERSION
    startup_order: list[str]


RuntimeResourceBootstrapDetail = Annotated[
    ResourceBootstrapDetail,
    Field(discriminator="kind"),
]


class RuntimeResourceBootstrapEnvelope(BaseModel):
    """
    运行时资源启动信封。
    """

    model_config = ConfigDict(extra="forbid")

    header: RuntimeResourceOperationHeader
    detail: RuntimeResourceBootstrapDetail

    @model_validator(mode="after")
    def validate_bootstrap_contract(self) -> RuntimeResourceBootstrapEnvelope:
        """
        校验启动操作公共头与扩展字段一致。
        """

        if self.header.kind != self.detail.kind:
            raise ValueError("资源启动 header.kind 必须与 detail.kind 一致。")
        if self.header.schema_version != self.detail.schema_version:
            raise ValueError("资源启动 header.schema_version 必须与 detail.schema_version 一致。")
        return self


class RuntimeResourceBootstrapper:
    """
    运行时资源启动装配器。
    """

    def build_contract(self, startup_order: list[str]) -> RuntimeResourceBootstrapEnvelope:
        """
        构建资源启动契约信封。
        """

        return RuntimeResourceBootstrapEnvelope(
            header=RuntimeResourceOperationHeader(
                operation_name=RESOURCE_BOOTSTRAP_OPERATION_NAME,
                target_resource=RESOURCE_BOOTSTRAP_TARGET_RESOURCE,
            ),
            detail=ResourceBootstrapDetail(startup_order=startup_order),
        )

    def startup(
        self,
        *,
        mount: SharedResourceLifecycle,
        settings: ApplicationSettings,
    ) -> None:
        """
        启动运行时资源。
        """

        LoggingEntryEnvironmentBridge().apply(settings.runtime.logging)
        self._initialize_http_resources(mount=mount, settings=settings)
        self._initialize_database(mount=mount, settings=settings)
        self._initialize_logging(mount=mount, settings=settings)
        mount.drain_pending_log_events()
        self._initialize_cache(mount=mount, settings=settings)
        self._initialize_message_and_task(mount=mount, settings=settings)

    def apply_message_runtime_state(
        self,
        *,
        mount: SharedResourceLifecycle,
        settings: ApplicationSettings,
    ) -> None:
        """
        应用消息运行时资源状态。
        """

        self._apply_message_runtime_state(mount=mount, settings=settings)

    def build_task_message_transport(self, settings: ApplicationSettings) -> MessageBus:
        """
        按消息后端配置构建真实消息总线对象。
        """

        return self._build_task_message_transport(settings)

    def _initialize_http_resources(
        self,
        *,
        mount: SharedResourceLifecycle,
        settings: ApplicationSettings,
    ) -> None:
        """
        初始化 HTTP 资源。
        """

        from src.infrastructure.resource_mount.shared_resource_constants import (
            RESOURCE_ASYNC_HTTP_CLIENT,
            RESOURCE_HTTP_CLIENT,
        )

        resource_set = mount.build_http_resource_set(settings)
        mount.attach_http_runtime(resource_set)
        mount.emit_runtime_lifecycle_log(
            resource_name=RESOURCE_HTTP_CLIENT,
            lifecycle_action=ResourceLifecycleAction.STARTUP,
            resource_status=RuntimeResourceStatus.READY,
            detail_text=None,
        )
        if resource_set.async_http_client is not None:
            mount.emit_runtime_lifecycle_log(
                resource_name=RESOURCE_ASYNC_HTTP_CLIENT,
                lifecycle_action=ResourceLifecycleAction.STARTUP,
                resource_status=RuntimeResourceStatus.READY,
                detail_text=None,
            )

    def _initialize_database(
        self,
        *,
        mount: SharedResourceLifecycle,
        settings: ApplicationSettings,
    ) -> None:
        """
        初始化数据库资源。
        """

        from src.infrastructure.resource_mount.shared_resource_constants import RESOURCE_DATABASE

        mount.mark_runtime_resource_state(
            RESOURCE_DATABASE,
            RuntimeResourceStatus.STARTING,
        )
        engine = mount.build_validated_database_engine(settings.runtime.database)
        session_factory = SqlAlchemySessionFactory(engine)
        db_session_manager = SharedDbSessionManager(session_factory)
        task_execution_store = TaskExecutionStore(
            session_manager=db_session_manager,
            metrics_registry=mount.get_metrics_registry(),
        )
        mount.install_database_runtime(
            session_factory=session_factory,
            db_session_manager=db_session_manager,
            task_execution_store=task_execution_store,
        )
        mount.upgrade_database_schema_if_enabled(settings)
        mount.bootstrap_admin_identity(settings)
        mount.mark_runtime_resource_ready(RESOURCE_DATABASE)
        mount.emit_runtime_lifecycle_log(
            resource_name=RESOURCE_DATABASE,
            lifecycle_action=ResourceLifecycleAction.STARTUP,
            resource_status=RuntimeResourceStatus.READY,
            detail_text=None,
        )

    def _initialize_logging(
        self,
        *,
        mount: SharedResourceLifecycle,
        settings: ApplicationSettings,
    ) -> None:
        """
        初始化日志资源。
        """

        from src.infrastructure.resource_mount.shared_resource_constants import (
            DATABASE_LOGGING_CONFIG_INVALID_MESSAGE,
            DATABASE_RESOURCE_NOT_READY_MESSAGE,
            RESOURCE_LOGGING,
        )

        mount.mark_runtime_resource_state(
            RESOURCE_LOGGING,
            RuntimeResourceStatus.STARTING,
        )
        if not settings.runtime.logging.enabled:
            mount.mark_runtime_resource_stopped(RESOURCE_LOGGING)
            mount.refresh_runtime_accessors()
            return
        db_session_manager = mount.get_database_session_manager()
        if db_session_manager is None:
            raise HttpFaultException(
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                error_code=CoreErrorCode.RESOURCE_NOT_READY,
                message=DATABASE_RESOURCE_NOT_READY_MESSAGE,
            )
        sink_detail = settings.runtime.logging.sink_detail
        if not isinstance(sink_detail, DatabaseLogSinkDetail):
            raise HttpFaultException(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                error_code=CoreErrorCode.CONFIG_INVALID,
                message=DATABASE_LOGGING_CONFIG_INVALID_MESSAGE,
            )
        logger = mount.get_runtime_logger()
        database_log_writer = DatabaseLogWriter(
            session_manager=db_session_manager,
            logger=logger,
            fallback_to_stdout=sink_detail.fallback_to_stdout,
        )
        log_buffer_dispatcher = LogBufferDispatcher(
            writer=database_log_writer,
            logger=logger,
            buffer_max_items=settings.runtime.logging.buffer_max_items,
            flush_interval_seconds=sink_detail.flush_interval_seconds,
            max_batch_size=sink_detail.max_batch_size,
            metrics_registry=mount.get_metrics_registry(),
        )
        structured_log_handler = StructuredLogHandler(log_buffer_dispatcher)
        mount.configure_runtime_structured_log_handler(structured_log_handler)
        mount.install_logging_runtime(
            database_log_writer=database_log_writer,
            log_buffer_dispatcher=log_buffer_dispatcher,
            structured_log_handler=structured_log_handler,
        )
        mount.mark_runtime_resource_ready(RESOURCE_LOGGING)
        mount.refresh_runtime_accessors()
        mount.emit_runtime_lifecycle_log(
            resource_name=RESOURCE_LOGGING,
            lifecycle_action=ResourceLifecycleAction.STARTUP,
            resource_status=RuntimeResourceStatus.READY,
            detail_text=None,
        )

    def _initialize_cache(
        self,
        *,
        mount: SharedResourceLifecycle,
        settings: ApplicationSettings,
    ) -> None:
        """
        初始化缓存资源。
        """

        from src.infrastructure.resource_mount.shared_resource_constants import (
            MEMORY_CACHE_CONFIG_INVALID_MESSAGE,
            PRODUCTION_MEMORY_CACHE_BLOCKED_MESSAGE,
            REDIS_CACHE_CONFIG_INVALID_MESSAGE,
            RESOURCE_CACHE,
        )
        from src.infrastructure.settings.application_settings import AppEnvironment

        mount.mark_runtime_resource_state(
            RESOURCE_CACHE,
            RuntimeResourceStatus.STARTING,
        )
        if (
            settings.app.environment == AppEnvironment.PRODUCTION
            and settings.runtime.cache.backend == CacheBackend.MEMORY
        ):
            raise HttpFaultException(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                error_code=CoreErrorCode.CONFIG_INVALID,
                message=PRODUCTION_MEMORY_CACHE_BLOCKED_MESSAGE,
            )
        cache_store: CacheStore
        if settings.runtime.cache.backend == CacheBackend.MEMORY:
            detail = settings.runtime.cache.backend_detail
            if not isinstance(detail, MemoryCacheBackendDetail):
                raise HttpFaultException(
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                    error_code=CoreErrorCode.CONFIG_INVALID,
                    message=MEMORY_CACHE_CONFIG_INVALID_MESSAGE,
                )
            cache_store = MemoryCacheStore(max_entries=detail.max_entries)
        else:
            detail = settings.runtime.cache.backend_detail
            if not isinstance(detail, RedisCacheBackendDetail):
                raise HttpFaultException(
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                    error_code=CoreErrorCode.CONFIG_INVALID,
                    message=REDIS_CACHE_CONFIG_INVALID_MESSAGE,
                )
            redis_cache = RedisCacheStore(
                redis_url=detail.redis_url,
                socket_connect_timeout_seconds=detail.socket_connect_timeout_seconds,
                max_connections=detail.max_connections,
            )
            redis_cache.assert_available()
            cache_store = redis_cache
        cache_service = CacheService(
            cache_store=cache_store,
            key_builder=CacheKeyBuilder(key_prefix=settings.runtime.cache.key_prefix),
            payload_codec=CachePayloadCodec(),
            policy_resolver=CachePolicyResolver(
                namespace_policies=settings.runtime.cache.namespace_policies,
                runtime_default_ttl_seconds=settings.runtime.cache.default_ttl_seconds,
            ),
            default_ttl_seconds=settings.runtime.cache.default_ttl_seconds,
            logger=mount.get_runtime_logger(),
        )
        auth_failure_throttle = AuthFailureThrottle(
            cache_service=cache_service,
            settings=settings.runtime.auth,
        )
        mount.install_cache_runtime(
            cache_store=cache_store,
            cache_service=cache_service,
            auth_failure_throttle=auth_failure_throttle,
        )
        mount.install_security_infrastructure(settings)
        mount.refresh_runtime_accessors()
        mount.mark_runtime_resource_ready(RESOURCE_CACHE)
        mount.emit_runtime_lifecycle_log(
            resource_name=RESOURCE_CACHE,
            lifecycle_action=ResourceLifecycleAction.STARTUP,
            resource_status=RuntimeResourceStatus.READY,
            detail_text=None,
        )

    def _initialize_message_and_task(
        self,
        *,
        mount: SharedResourceLifecycle,
        settings: ApplicationSettings,
    ) -> None:
        """
        初始化消息与任务资源。
        """

        from src.infrastructure.resource_mount.shared_resource_constants import (
            RESOURCE_TASK,
            TASK_RESOURCE_READY_DETAIL,
        )

        self._validate_task_message_topology(settings)
        message_bus = self.build_task_message_transport(settings)
        self._apply_message_runtime_state(mount=mount, settings=settings)
        mount.mark_runtime_resource_state(
            RESOURCE_TASK,
            RuntimeResourceStatus.STARTING,
        )
        registration_registry = mount.get_task_registration_registry()
        runtime_assembly = mount.build_task_runtime_assembly(
            settings=settings,
            message_bus=message_bus,
            registration_registry=registration_registry,
        )
        mount.install_task_runtime(
            registration_registry=registration_registry,
            message_bus=message_bus,
            runtime_assembly=runtime_assembly,
        )
        mount.publish_reserved_task_outbox()
        mount.mark_runtime_resource_ready(
            RESOURCE_TASK,
            TASK_RESOURCE_READY_DETAIL,
        )
        mount.emit_runtime_lifecycle_log(
            resource_name=RESOURCE_TASK,
            lifecycle_action=ResourceLifecycleAction.STARTUP,
            resource_status=RuntimeResourceStatus.READY,
            detail_text=None,
        )

    def _apply_message_runtime_state(
        self,
        *,
        mount: SharedResourceLifecycle,
        settings: ApplicationSettings,
    ) -> None:
        """
        应用消息运行时状态。
        """

        from src.infrastructure.resource_mount.shared_resource_constants import (
            RABBITMQ_CONFIG_INVALID_MESSAGE,
            RABBITMQ_PROBE_FAILED_MESSAGE,
            RESOURCE_TASK_MESSAGE_TRANSPORT,
        )

        mount.mark_runtime_resource_state(
            RESOURCE_TASK_MESSAGE_TRANSPORT,
            RuntimeResourceStatus.STARTING,
        )
        if settings.runtime.message.backend == MessageBackend.RABBITMQ:
            detail = settings.runtime.message.backend_detail
            if not isinstance(detail, RabbitMqMessageBackendDetail):
                raise HttpFaultException(
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                    error_code=CoreErrorCode.CONFIG_INVALID,
                    message=RABBITMQ_CONFIG_INVALID_MESSAGE,
                )
            rabbitmq_gateway = RabbitMqMessageGateway(detail.rabbitmq_url)
            if detail.startup_probe_enabled:
                try:
                    rabbitmq_gateway.assert_available(
                        timeout_seconds=detail.startup_probe_timeout_seconds
                    )
                except HttpFaultException as exc:
                    mount.record_task_failure(
                        TaskFailureRecord(
                            task_id=RESOURCE_TASK_MESSAGE_TRANSPORT,
                            job_kind=settings.modules.task.default_job_kind,
                            message=RABBITMQ_PROBE_FAILED_MESSAGE,
                            retry_count=STARTUP_PROBE_RETRY_COUNT,
                            backend=settings.runtime.task.backend,
                            stage=TaskFailureStage.STARTUP_PROBE,
                            last_error=exc.detail or exc.message,
                            queue_name=None,
                            payload_kind=None,
                        )
                    )
                    raise
            if not rabbitmq_gateway.validate_configuration():
                raise HttpFaultException(
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                    error_code=CoreErrorCode.CONFIG_INVALID,
                    message=RABBITMQ_CONFIG_INVALID_MESSAGE,
                )
        mount.mark_runtime_resource_ready(
            RESOURCE_TASK_MESSAGE_TRANSPORT,
            self._build_message_resource_ready_detail(settings),
        )
        mount.emit_runtime_lifecycle_log(
            resource_name=RESOURCE_TASK_MESSAGE_TRANSPORT,
            lifecycle_action=ResourceLifecycleAction.STARTUP,
            resource_status=RuntimeResourceStatus.READY,
            detail_text=None,
        )

    def _build_task_message_transport(self, settings: ApplicationSettings) -> MessageBus:
        """
        按消息后端配置构建真实消息总线对象。
        """

        detail = settings.runtime.message.backend_detail
        if isinstance(detail, LocalMessageBackendDetail):
            return LocalMessageBus(max_items=detail.max_items)
        if isinstance(detail, RabbitMqMessageBackendDetail):
            return RabbitMqMessageBus(detail=detail)
        raise TypeError("不支持的消息后端配置。")

    def _build_message_resource_ready_detail(
        self,
        settings: ApplicationSettings,
    ) -> str:
        """
        构建消息资源就绪详情。
        """

        from src.infrastructure.resource_mount.shared_resource_constants import (
            FUNBOOST_RABBITMQ_BROKER_RESOURCE_DETAIL,
            LOCAL_MESSAGE_RESOURCE_READY_DETAIL,
            RABBITMQ_MESSAGE_RESOURCE_READY_DETAIL,
        )

        if settings.runtime.message.backend == MessageBackend.RABBITMQ:
            return (
                f"{RABBITMQ_MESSAGE_RESOURCE_READY_DETAIL}"
                f"{MESSAGE_RESOURCE_DETAIL_SEPARATOR}"
                f"{FUNBOOST_RABBITMQ_BROKER_RESOURCE_DETAIL}"
            )
        return LOCAL_MESSAGE_RESOURCE_READY_DETAIL

    def _validate_task_message_topology(
        self,
        settings: ApplicationSettings,
    ) -> None:
        """
        校验任务后端与消息总线组合。
        """

        if (
            settings.runtime.task.backend == TaskBackend.LOCAL
            and settings.runtime.message.backend == MessageBackend.RABBITMQ
        ):
            raise HttpFaultException(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                error_code=CoreErrorCode.CONFIG_INVALID,
                message=LOCAL_TASK_RABBITMQ_MESSAGE_BLOCKED_MESSAGE,
            )
