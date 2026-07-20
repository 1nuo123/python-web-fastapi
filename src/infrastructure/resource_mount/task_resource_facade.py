"""任务运行时资源。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

from http import HTTPStatus

from pydantic import BaseModel, ValidationError

from src.application.ports.task_runtime_port import TaskRegistrationRuntimeSnapshot
from src.core.exception_contract.error_code_catalog_contract import CoreErrorCode
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.task_contract.message_bus_contract import (
    MessageBus,
    MessageBusBackend,
    TaskMessageEnvelope,
)
from src.core.task_contract.task_dispatcher_contract import (
    TaskDispatcher,
    TaskDispatchResultPayload,
)
from src.core.task_contract.task_execution_record_contract import (
    TaskExecutionRecordEnvelope,
    TaskExecutionStatus,
)
from src.core.task_contract.task_handler_contract import TaskHandler
from src.core.task_contract.task_registration_contract import TaskRegistrationEnvelope
from src.core.task_contract.task_runtime_contract import (
    LocalTaskBackendDetail,
    MessageBackend,
    TaskBackend,
    TaskRuntimeMode,
)
from src.infrastructure.resource_mount.shared_resource_constants import (
    LOCAL_MESSAGE_LIST_UNAVAILABLE_MESSAGE,
    MESSAGE_BUS_NOT_READY_MESSAGE,
    TASK_DISPATCHER_NOT_READY_MESSAGE,
    TASK_OUTBOX_PUBLISHER_NOT_READY_MESSAGE,
    TASK_PAYLOAD_HANDLER_MISSING_MESSAGE,
    TASK_PAYLOAD_JSON_INVALID_MESSAGE,
)
from src.infrastructure.resource_mount.shared_resource_lifecycle import SharedResourceLifecycle
from src.infrastructure.resource_mount.shared_resource_models import (
    RuntimeBundle,
    TaskRuntimeAccessor,
)
from src.infrastructure.task.failed_task_recorder import (
    FailedTaskRecorder,
)
from src.infrastructure.task.local_message_bus import LocalMessageBus
from src.infrastructure.task.task_execution_outbox_publisher import (
    TASK_EXECUTION_OUTBOX_DEFAULT_LIMIT,
    TaskExecutionOutboxPublishResult,
)
from src.infrastructure.task.task_registration_registry import (
    RegisteredTaskBinding,
    TaskBootstrapSnapshot,
    TaskRegistrationRegistry,
)


class TaskResourceFacade(SharedResourceLifecycle):
    """任务运行时资源门面。"""

    def get_task_message_transport(self) -> MessageBus:
        """
        获取消息总线。
        """

        task_accessor = self.read_runtime_bundle().task_accessor
        if task_accessor.message_bus is None:
            raise HttpFaultException(
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                error_code=CoreErrorCode.RESOURCE_NOT_READY,
                message=MESSAGE_BUS_NOT_READY_MESSAGE,
            )
        return task_accessor.message_bus

    def get_task_dispatcher(self) -> TaskDispatcher:
        """
        获取任务分发器。
        """

        task_accessor = self.read_runtime_bundle().task_accessor
        if task_accessor.dispatcher is None:
            raise HttpFaultException(
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                error_code=CoreErrorCode.RESOURCE_NOT_READY,
                message=TASK_DISPATCHER_NOT_READY_MESSAGE,
            )
        return task_accessor.dispatcher

    def get_task_registration_registry(self) -> TaskRegistrationRegistry:
        """
        获取任务注册中心。
        """

        return self.read_runtime_bundle().task_accessor.registration_registry

    def get_enabled_task_registration(self, job_kind: str) -> TaskRegistrationEnvelope:
        """
        获取启用任务注册。
        """

        return self.get_enabled_task_registration_for_backend(
            job_kind,
            backend=self.get_current_task_backend(),
        )

    def get_current_task_backend(self) -> TaskBackend:
        """
        获取当前任务运行时后端。
        """

        return self.read_runtime_bundle().settings.runtime.task.backend

    def get_current_configured_transport_backend(self) -> MessageBackend:
        """
        Read the configured task message transport backend.
        """

        return self.read_runtime_bundle().settings.runtime.message.backend

    def get_current_transport_backend(self) -> MessageBusBackend:
        """
        获取当前消息总线真实挂载后端。
        """

        return self.get_task_message_transport().backend

    def get_current_task_runtime_mode(self) -> TaskRuntimeMode:
        """
        获取当前任务运行时节点模式。
        """

        task_backend = self.get_current_task_backend()
        if task_backend == TaskBackend.LOCAL:
            if self.is_local_inline_execute_enabled():
                return TaskRuntimeMode.LOCAL_INLINE
            return TaskRuntimeMode.LOCAL_QUEUED
        if self.is_task_worker_enabled():
            return TaskRuntimeMode.FUNBOOST_CONSUMER
        return TaskRuntimeMode.FUNBOOST_PRODUCER

    def is_task_worker_enabled(self) -> bool:
        """
        获取当前节点是否启用任务消费或工作器。
        """

        return self.read_runtime_bundle().settings.runtime.task.worker_enabled

    def is_local_inline_execute_enabled(self) -> bool:
        """
        获取当前本地任务后端是否启用内联执行。
        """

        settings = self.read_runtime_bundle().settings
        if settings.runtime.task.backend != TaskBackend.LOCAL:
            return False
        detail = settings.runtime.task.backend_detail
        if not isinstance(detail, LocalTaskBackendDetail):
            raise TypeError("本地任务后端扩展配置类型不正确。")
        return detail.inline_execute_enabled

    def list_local_task_messages(self) -> list[TaskMessageEnvelope]:
        """
        读取本地消息总线中的任务消息列表。

        :returns: 本地任务消息列表。
        :rtype: list[TaskMessageEnvelope]
        :raises HttpFaultException: 当当前消息总线不是本地后端时抛出。
        """

        message_bus = self.get_task_message_transport()
        if not isinstance(message_bus, LocalMessageBus):
            raise HttpFaultException(
                status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
                error_code=CoreErrorCode.REQUEST_INVALID,
                message=LOCAL_MESSAGE_LIST_UNAVAILABLE_MESSAGE,
            )
        return message_bus.list_messages()

    def get_enabled_task_registration_for_backend(
        self,
        job_kind: str,
        *,
        backend: TaskBackend,
    ) -> TaskRegistrationEnvelope:
        """
        按后端获取启用任务注册。
        """

        return self.read_runtime_bundle().task_accessor.registration_registry.get_enabled_registration_for_backend(
            job_kind,
            backend=backend,
        )

    def get_default_job_kind(self) -> str:
        """
        获取默认任务类型。
        """

        return self.read_runtime_bundle().settings.modules.task.default_job_kind

    def get_default_retry_limit(self) -> int:
        """
        获取默认任务重试次数。
        """

        return self.read_runtime_bundle().settings.modules.task.default_retry_limit

    def dispatch_task_message(
        self,
        task_message: TaskMessageEnvelope,
    ) -> TaskDispatchResultPayload:
        """
        派发任务消息。
        """

        return self.get_task_dispatcher().dispatch(task_message)

    def get_task_execution_record(
        self,
        task_id: str,
    ) -> TaskExecutionRecordEnvelope | None:
        """
        按任务标识读取执行记录。
        """

        return self.get_task_execution_store().get_by_task_id(task_id)

    def list_task_execution_records(
        self,
        *,
        limit: int,
        status: TaskExecutionStatus | None = None,
        job_kind: str | None = None,
    ) -> list[TaskExecutionRecordEnvelope]:
        """
        查询任务执行记录。
        """

        return self.get_task_execution_store().list_records(
            limit=limit,
            status=status,
            job_kind=job_kind,
        )

    def list_task_registration_snapshots(
        self,
    ) -> list[TaskRegistrationRuntimeSnapshot]:
        """
        读取全部任务注册运行时快照。
        """

        runtime_bundle = self.read_runtime_bundle()
        registry = runtime_bundle.task_accessor.registration_registry
        current_backend = runtime_bundle.settings.runtime.task.backend
        return [
            TaskRegistrationRuntimeSnapshot(
                registration=registration,
                handler_bound=registry.get_binding(registration.header.job_kind) is not None,
                payload_model_name=self._read_payload_model_name(registration.header.job_kind),
                registration_backend=registration.header.backend,
                current_runtime_backend=current_backend,
                active_for_current_runtime=(
                    registration.header.enabled and registration.header.backend == current_backend
                ),
            )
            for registration in registry.list_registrations()
        ]

    def validate_task_payload_json(
        self,
        *,
        job_kind: str,
        payload_json: str,
    ) -> BaseModel:
        """
        按任务绑定的载荷模型校验 JSON 字符串。
        """

        self.get_enabled_task_registration_for_backend(
            job_kind,
            backend=self.get_current_task_backend(),
        )
        binding = self.read_runtime_bundle().task_accessor.registration_registry.get_binding(
            job_kind
        )
        if binding is None:
            raise HttpFaultException(
                status_code=HTTPStatus.BAD_REQUEST,
                error_code=CoreErrorCode.CONFIG_INVALID,
                message=TASK_PAYLOAD_HANDLER_MISSING_MESSAGE.format(job_kind=job_kind),
            )
        try:
            return binding.payload_model.model_validate_json(payload_json)
        except ValidationError as exc:
            raise HttpFaultException(
                status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
                error_code=CoreErrorCode.REQUEST_INVALID,
                message=TASK_PAYLOAD_JSON_INVALID_MESSAGE.format(job_kind=job_kind),
                detail=str(exc),
            ) from exc

    def get_failed_task_recorder(self) -> FailedTaskRecorder:
        """
        获取失败任务记录器。
        """

        return self._failed_task_recorder

    def register_task_handler(
        self,
        job_kind: str,
        handler: TaskHandler[BaseModel],
        *,
        payload_model: type[BaseModel],
    ) -> None:
        """
        注册任务处理器。
        """

        self.register_task_binding(
            RegisteredTaskBinding(
                job_kind=job_kind,
                payload_model=payload_model,
                handler=handler,
            )
        )

    def register_task_binding(
        self,
        binding: RegisteredTaskBinding[BaseModel],
    ) -> None:
        """
        注册任务绑定。
        """

        with self._reload_lock:
            self._worker_supervisor.register_binding(binding)
            self._task_runtime_accessor.registration_registry.register_binding(binding)
            self._rebuild_task_runtime_after_binding_change()

    def get_task_bootstrap_snapshot(self) -> TaskBootstrapSnapshot | None:
        """
        获取任务装配快照。
        """

        return self.read_runtime_bundle().task_accessor.bootstrap_snapshot

    def publish_reserved_task_outbox(
        self,
        *,
        limit: int = TASK_EXECUTION_OUTBOX_DEFAULT_LIMIT,
    ) -> TaskExecutionOutboxPublishResult:
        """
        重扫并发布已预占但尚未发布的任务 Outbox 消息。

        :param limit: 本轮扫描上限。
        :type limit: int
        :returns: Outbox 发布结果。
        :rtype: TaskExecutionOutboxPublishResult
        :raises HttpFaultException: 当任务 Outbox 发布器尚未就绪时抛出资源异常。
        """

        task_accessor = self.read_runtime_bundle().task_accessor
        if task_accessor.outbox_publisher is None:
            raise HttpFaultException(
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                error_code=CoreErrorCode.RESOURCE_NOT_READY,
                message=TASK_OUTBOX_PUBLISHER_NOT_READY_MESSAGE,
            )
        return task_accessor.outbox_publisher.publish_reserved(limit=limit)

    def _rebuild_task_runtime_after_binding_change(self) -> None:
        """
        在运行时已启动时重新装配任务分发器。
        """

        current_runtime_bundle = self.read_runtime_bundle()
        current_settings = current_runtime_bundle.settings
        current_registration_registry = current_runtime_bundle.task_accessor.registration_registry
        self._task_runtime_accessor = TaskRuntimeAccessor(
            registration_registry=current_registration_registry,
            message_bus=self._task_runtime_accessor.message_bus,
            dispatcher=self._task_runtime_accessor.dispatcher,
            outbox_publisher=self._task_runtime_accessor.outbox_publisher,
            bootstrap_snapshot=current_registration_registry.build_bootstrap_snapshot(
                current_settings.runtime.task.backend
            ),
        )
        if (
            self._task_runtime_accessor.dispatcher is None
            or self._task_runtime_accessor.message_bus is None
        ):
            return
        runtime_assembly = self._task_runtime_manager.build_runtime(
            settings=current_settings,
            message_bus=self._task_runtime_accessor.message_bus,
            registration_registry=current_registration_registry,
            task_execution_store=self.get_task_execution_store(),
        )
        previous_dispatcher = self._task_runtime_accessor.dispatcher
        self._task_runtime_accessor = TaskRuntimeAccessor(
            registration_registry=current_registration_registry,
            message_bus=self._task_runtime_accessor.message_bus,
            dispatcher=runtime_assembly.dispatcher,
            outbox_publisher=runtime_assembly.outbox_publisher,
            bootstrap_snapshot=runtime_assembly.bootstrap_snapshot,
        )
        self._runtime_generation += 1
        self._runtime_bundle = RuntimeBundle(
            settings=current_settings,
            http_accessor=self._http_runtime_accessor,
            task_accessor=self._task_runtime_accessor,
            runtime_dependencies=self._build_runtime_dependency_set(
                settings=current_settings,
                auth_failure_throttle=self._auth_failure_throttle,
            ),
            capacity_policy=self._capacity_policy_resolver.resolve(current_settings),
            generation=self._runtime_generation,
        )
        previous_dispatcher.shutdown()

    def _read_payload_model_name(self, job_kind: str) -> str | None:
        """
        读取任务载荷模型名称。
        """

        binding = self.read_runtime_bundle().task_accessor.registration_registry.get_binding(
            job_kind
        )
        if binding is None:
            return None
        return binding.payload_model.__name__
