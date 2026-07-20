"""
任务运行时管理器基础设施模块。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.core.task_contract.message_bus_contract import MessageBus
from src.core.task_contract.task_dispatcher_contract import TaskDispatcher
from src.core.task_contract.task_runtime_contract import (
    FunboostTaskBackendDetail,
    LocalTaskBackendDetail,
    RabbitMqMessageBackendDetail,
    TaskBackend,
)
from src.infrastructure.logging.logging_entry_environment_bridge import (
    LoggingEntryEnvironmentBridge,
)
from src.infrastructure.settings.application_settings import ApplicationSettings
from src.infrastructure.task.failed_task_recorder import (
    FailedTaskRecorder,
    TaskFailureRecord,
)
from src.infrastructure.task.local_task_dispatcher import LocalTaskDispatcher
from src.infrastructure.task.task_execution_outbox_publisher import (
    TaskExecutionOutboxPublisher,
)
from src.infrastructure.task.task_execution_store import TaskExecutionStore
from src.infrastructure.task.task_registration_registry import (
    TaskBootstrapSnapshot,
    TaskRegistrationRegistry,
)

if TYPE_CHECKING:
    from src.infrastructure.task.funboost_task_bootstrapper import FunboostTaskBootstrapper


@dataclass(slots=True)
class TaskRuntimeAssembly:
    """
    任务运行时装配结果。
    """

    dispatcher: TaskDispatcher
    bootstrapper: FunboostTaskBootstrapper | None
    outbox_publisher: TaskExecutionOutboxPublisher
    bootstrap_snapshot: TaskBootstrapSnapshot


class TaskRuntimeManager:
    """
    任务运行时管理器。
    """

    def __init__(
        self,
        *,
        failed_task_recorder: FailedTaskRecorder,
        failure_callback: Callable[[TaskFailureRecord], None],
        logger: logging.Logger,
    ) -> None:
        """
        初始化任务运行时管理器。

        :param failed_task_recorder: 统一失败任务记录器。
        :type failed_task_recorder: FailedTaskRecorder
        :param failure_callback: 统一失败记录回调。
        :type failure_callback: Callable[[TaskFailureRecord], None]
        :returns: 无返回值。
        :rtype: None
        """

        self._failed_task_recorder = failed_task_recorder
        self._failure_callback = failure_callback
        self._logger = logger
        self._logging_entry_bridge = LoggingEntryEnvironmentBridge()

    def build_runtime(
        self,
        *,
        settings: ApplicationSettings,
        message_bus: MessageBus,
        registration_registry: TaskRegistrationRegistry,
        task_execution_store: TaskExecutionStore,
    ) -> TaskRuntimeAssembly:
        """
        构建任务运行时。

        :param settings: 已通过校验的应用配置快照。
        :type settings: ApplicationSettings
        :param message_bus: 当前共享消息总线。
        :type message_bus: MessageBus
        :param registration_registry: 当前任务注册中心。
        :type registration_registry: TaskRegistrationRegistry
        :returns: 返回任务运行时装配结果。
        :rtype: TaskRuntimeAssembly
        """

        self._logging_entry_bridge.apply(settings.runtime.logging)
        if self._should_require_handler_completeness(settings=settings):
            registration_registry.assert_all_enabled_tasks_bound(settings.runtime.task.backend)
        elif self._should_require_producer_declaration(settings=settings):
            registration_registry.assert_enabled_tasks_declarable_for_producer(
                settings.runtime.task.backend
            )
        if settings.runtime.task.backend == TaskBackend.LOCAL:
            local_detail = self._read_local_task_detail(settings)
            local_dispatcher = LocalTaskDispatcher(
                message_bus=message_bus,
                registration_registry=registration_registry,
                failed_task_recorder=self._failed_task_recorder,
                task_execution_store=task_execution_store,
                worker_enabled=settings.runtime.task.worker_enabled,
                inline_execute_enabled=local_detail.inline_execute_enabled,
                retry_delay_seconds=local_detail.retry_delay_seconds,
                retry_backoff_multiplier=local_detail.retry_backoff_multiplier,
                retry_max_delay_seconds=local_detail.retry_max_delay_seconds,
                failure_callback=self._failure_callback,
            )
            outbox_publisher = TaskExecutionOutboxPublisher(
                task_execution_store=task_execution_store,
                local_message_bus=message_bus,
                logger=self._logger,
                background_enabled=True,
            )
            return TaskRuntimeAssembly(
                dispatcher=local_dispatcher,
                bootstrapper=None,
                outbox_publisher=outbox_publisher,
                bootstrap_snapshot=registration_registry.build_bootstrap_snapshot(
                    settings.runtime.task.backend
                ),
            )
        from src.infrastructure.task.funboost_task_bootstrapper import (
            FunboostTaskBootstrapper,
        )
        from src.infrastructure.task.funboost_task_dispatcher import (
            FunboostTaskDispatcher,
        )

        funboost_detail = self._read_funboost_task_detail(settings)
        rabbitmq_detail = settings.runtime.message.backend_detail
        if not isinstance(rabbitmq_detail, RabbitMqMessageBackendDetail):
            raise TypeError("Funboost 任务运行时必须使用 RabbitMQ 消息配置。")
        bootstrapper = FunboostTaskBootstrapper(
            registration_registry=registration_registry,
            runtime_detail=funboost_detail,
            message_detail=rabbitmq_detail,
            task_execution_store=task_execution_store,
            entry_project_name=settings.runtime.logging.entry_project_name,
            failure_callback=self._failure_callback,
        )
        bootstrapper.configure_broker_connection()
        if settings.runtime.task.worker_enabled:
            self.sync_bindings_to_bootstrapper(
                bootstrapper=bootstrapper,
                registration_registry=registration_registry,
            )
            bootstrapper.start_consumers()
        else:
            self.sync_publishers_to_bootstrapper(
                bootstrapper=bootstrapper,
                registration_registry=registration_registry,
            )
        funboost_dispatcher = FunboostTaskDispatcher(
            registration_registry=registration_registry,
            bootstrapper=bootstrapper,
            failed_task_recorder=self._failed_task_recorder,
            task_execution_store=task_execution_store,
            worker_enabled=settings.runtime.task.worker_enabled,
            failure_callback=self._failure_callback,
        )
        outbox_publisher = TaskExecutionOutboxPublisher(
            task_execution_store=task_execution_store,
            local_message_bus=message_bus,
            logger=self._logger,
            funboost_bootstrapper=bootstrapper,
            background_enabled=True,
        )
        return TaskRuntimeAssembly(
            dispatcher=funboost_dispatcher,
            bootstrapper=bootstrapper,
            outbox_publisher=outbox_publisher,
            bootstrap_snapshot=registration_registry.build_bootstrap_snapshot(
                settings.runtime.task.backend
            ),
        )

    def sync_bindings_to_bootstrapper(
        self,
        *,
        bootstrapper: FunboostTaskBootstrapper,
        registration_registry: TaskRegistrationRegistry,
    ) -> None:
        """
        同步任务绑定到 Funboost 装配器。

        :param bootstrapper: 当前 Funboost 任务装配器。
        :type bootstrapper: FunboostTaskBootstrapper
        :param registration_registry: 当前任务注册中心。
        :type registration_registry: TaskRegistrationRegistry
        :returns: 无返回值。
        :rtype: None
        """

        for registration in registration_registry.list_registrations_by_backend(
            TaskBackend.FUNBOOST
        ):
            if not registration.header.enabled:
                continue
            bootstrapper.register_consumer(registration.header.job_kind)

    def sync_publishers_to_bootstrapper(
        self,
        *,
        bootstrapper: FunboostTaskBootstrapper,
        registration_registry: TaskRegistrationRegistry,
    ) -> None:
        """
        同步 producer-only 发布器到 Funboost 装配器。
        """

        for registration in registration_registry.list_registrations_by_backend(
            TaskBackend.FUNBOOST
        ):
            if not registration.header.enabled:
                continue
            bootstrapper.register_publisher(registration.header.job_kind)

    def _should_require_handler_completeness(
        self,
        *,
        settings: ApplicationSettings,
    ) -> bool:
        """
        判断当前节点是否需要完整处理器绑定。
        """

        if settings.runtime.task.backend == TaskBackend.LOCAL:
            return self._read_local_task_detail(settings).inline_execute_enabled
        return settings.runtime.task.worker_enabled

    def _read_local_task_detail(
        self,
        settings: ApplicationSettings,
    ) -> LocalTaskBackendDetail:
        """读取本地任务扩展配置。"""

        detail = settings.runtime.task.backend_detail
        if not isinstance(detail, LocalTaskBackendDetail):
            raise TypeError("本地任务后端扩展配置类型不正确。")
        return detail

    def _read_funboost_task_detail(
        self,
        settings: ApplicationSettings,
    ) -> FunboostTaskBackendDetail:
        """读取 Funboost 任务扩展配置。"""

        detail = settings.runtime.task.backend_detail
        if not isinstance(detail, FunboostTaskBackendDetail):
            raise TypeError("Funboost 任务后端扩展配置类型不正确。")
        return detail

    def _should_require_producer_declaration(
        self,
        *,
        settings: ApplicationSettings,
    ) -> bool:
        """
        判断当前节点是否需要 producer-only 任务声明。
        """

        return (
            settings.runtime.task.backend == TaskBackend.FUNBOOST
            and not settings.runtime.task.worker_enabled
        )
