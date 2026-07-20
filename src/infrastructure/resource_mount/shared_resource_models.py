"""共享运行时资源模型。"""

from __future__ import annotations

from dataclasses import dataclass

from src.application.authorization_guard import AuthorizationGuard
from src.core.concurrency_contract.runtime_capacity_contract import RuntimeCapacityPolicy
from src.core.logging_contract.log_event_contract import (
    LogEventEnvelope,
)
from src.core.task_contract.message_bus_contract import (
    MessageBus,
)
from src.core.task_contract.task_dispatcher_contract import (
    TaskDispatcher,
)
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
from src.infrastructure.logging.log_event_builder import LogEventBuilder
from src.infrastructure.logging.structured_log_handler import StructuredLogHandler
from src.infrastructure.resource_slot.shared_http_resource_manager import (
    SharedHttpResourceSet,
)
from src.infrastructure.settings.application_settings import (
    ApplicationSettings,
)
from src.infrastructure.task.task_execution_outbox_publisher import (
    TaskExecutionOutboxPublisher,
)
from src.infrastructure.task.task_registration_registry import (
    TaskBootstrapSnapshot,
    TaskRegistrationRegistry,
)
from src.infrastructure.task.task_runtime_manager import (
    TaskRuntimeAssembly,
)


@dataclass(frozen=True, slots=True)
class RuntimeDependencySet:
    """
    运行时依赖集合。
    """

    password_hasher: PasswordHasher
    jwt_token_service: JwtTokenService
    bootstrap_admin_synchronizer: BootstrapAdminSynchronizer
    auth_failure_throttle: AuthFailureThrottle | None


@dataclass(frozen=True, slots=True)
class TaskRuntimeSet:
    """
    任务运行时集合。
    """

    registration_registry: TaskRegistrationRegistry
    message_bus: MessageBus
    runtime_assembly: TaskRuntimeAssembly


@dataclass(frozen=True, slots=True)
class HttpRuntimeAccessor:
    """
    HTTP 运行时访问器。
    """

    resource_set: SharedHttpResourceSet | None


@dataclass(frozen=True, slots=True)
class TaskRuntimeAccessor:
    """
    任务运行时访问器。
    """

    registration_registry: TaskRegistrationRegistry
    message_bus: MessageBus | None
    dispatcher: TaskDispatcher | None
    outbox_publisher: TaskExecutionOutboxPublisher | None
    bootstrap_snapshot: TaskBootstrapSnapshot | None


@dataclass(frozen=True, slots=True)
class RuntimeBundle:
    """
    运行时不可变快照包。
    """

    settings: ApplicationSettings
    http_accessor: HttpRuntimeAccessor
    task_accessor: TaskRuntimeAccessor
    runtime_dependencies: RuntimeDependencySet
    capacity_policy: RuntimeCapacityPolicy
    generation: int


@dataclass(slots=True)
class RetiredRuntimeResources:
    """
    待延迟释放的旧运行时资源。
    """

    http_resources: SharedHttpResourceSet | None
    outbox_publisher: TaskExecutionOutboxPublisher | None
    dispatcher: TaskDispatcher | None
    message_bus: MessageBus | None


@dataclass(slots=True)
class AuthSupportAccessor:
    """
    鉴权支持访问器。
    """

    password_hasher: PasswordHasher
    jwt_token_service: JwtTokenService
    auth_failure_throttle: AuthFailureThrottle | None
    oauth2_scheme_provider: OAuth2SchemeProvider
    authorization_policy_evaluator: AuthorizationPolicyEvaluator
    authorization_guard: AuthorizationGuard


@dataclass(slots=True)
class LoggingSupportAccessor:
    """
    日志支持访问器。
    """

    log_event_builder: LogEventBuilder
    structured_log_handler: StructuredLogHandler | None
    pending_log_events: list[LogEventEnvelope]
